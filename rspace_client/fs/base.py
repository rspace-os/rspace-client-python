"""
Shared base class for the RSpace PyFilesystem implementations.

Provides, so that every branch (Gallery, Inventory, Workspace) behaves the same:

* a path style: ``name`` shows a record's own name, ``labelled`` shows ``Name [GID]``
  and ``id`` shows bare global IDs. A segment carrying a global ID resolves under
  every style; a *bare name* resolves only under ``name``, through ``_lookup``, which
  matches it against the parent's listing;
* a write posture: read-only by default, ``writable=True`` enables uploads and
  folder creation, ``allow_delete=True`` enables removals;
* ``make_info`` which builds a PyFilesystem ``Info`` whose ``name`` is the last
  path segment, whose ``details`` carry ``size``, ``created`` and
  ``modified`` as epoch seconds (needed by Galaxy and other consumers of
  ``filterdir(namespaces=["details"])``), and whose ``rspace`` namespace holds the
  raw RSpace record including the human-readable ``name``;
* ``listdir``/``scandir``, which subclasses feed from a single listing call via
  ``_scan`` instead of one ``getinfo`` request per child, and which keep the
  segments in a listing unique even when two records share a name;
* ``stream_pages``, which turns any paginated RSpace response into a lazy stream of
  records by following its ``next`` links only as far as the consumer reads;
* the ``openbin`` read/write shim that used to be duplicated in both filesystems.
"""
from __future__ import annotations

import functools
import itertools
from dataclasses import dataclass
from datetime import datetime, timezone
from io import BytesIO
from typing import (Any, BinaryIO, Callable, Collection, Dict, Iterable, Iterator, List, Mapping, Optional,
                    Text, Tuple)

from fs import errors
from fs.base import FS
from fs.enums import ResourceType
from fs.info import Info
from fs.mode import Mode
from fs.permissions import Permissions
from fs.path import basename, join
from fs.subfs import SubFS

from rspace_client.client_base import ClientBase
from rspace_client.exceptions import ApiError, AuthenticationError, RSpaceConnectionError

from . import paths


# ------------------------------------------------------------------ error translation
#
# PyFilesystem callers (``exists``, ``walk``, ``copy``, Galaxy's file source) expect
# ``fs.errors.FSError`` subclasses. The RSpace clients raise their own exceptions, so every
# public filesystem method translates them at the boundary, once, here. Statuses that carry a
# domain meaning (400, 409, 422: a section mismatch, a refused link) are left as they are, so
# the caller still sees the server's own explanation.

#: Public methods whose first argument is a path and which may call the server.
_TRANSLATED_METHODS = ("getinfo", "scandir", "listdir", "download", "upload", "openbin",
                       "makedir", "remove", "removedir", "setinfo", "link")


def fs_error_for(exc: Exception, path: Text) -> Optional[errors.FSError]:
    """The ``fs.errors`` exception that stands for a client exception, or None to re-raise."""
    if isinstance(exc, RSpaceConnectionError):
        return errors.RemoteConnectionError(path, exc=exc, msg=f"{path!r}: {exc}")
    if isinstance(exc, AuthenticationError):
        return errors.PermissionDenied(path, exc=exc, msg=f"{path!r}: {exc}")
    status = getattr(exc, "response_status_code", None)
    if status == 404:
        return errors.ResourceNotFound(path, exc=exc)
    if status == 403:
        return errors.PermissionDenied(path, exc=exc, msg=f"{path!r}: {exc}")
    if status is not None and status >= 500:
        return errors.RemoteConnectionError(path, exc=exc, msg=f"{path!r}: {exc}")
    return None


def _translating_iterator(iterator: Iterator, path: Text) -> Iterator:
    try:
        yield from iterator
    except (ApiError, AuthenticationError, RSpaceConnectionError) as exc:
        translated = fs_error_for(exc, path)
        if translated is None:
            raise
        raise translated from exc


def writes(method):
    """Mark a method that changes the server: it is refused unless ``writable=True``."""
    @functools.wraps(method)
    def wrapper(self, path, *args, **kwargs):
        self._require_writable(path)
        return method(self, path, *args, **kwargs)
    return wrapper


def deletes(method):
    """Mark a method that removes something: it is refused unless ``allow_delete=True``."""
    @functools.wraps(method)
    def wrapper(self, path, *args, **kwargs):
        self._require_delete(path)
        return method(self, path, *args, **kwargs)
    return wrapper


def translate_api_errors(method):
    """Wrap a filesystem method so RSpace client errors surface as ``fs.errors``."""
    if getattr(method, "_translates_api_errors", False):
        return method

    @functools.wraps(method)
    def wrapper(self, path, *args, **kwargs):
        try:
            result = method(self, path, *args, **kwargs)
        except (ApiError, AuthenticationError, RSpaceConnectionError) as exc:
            translated = fs_error_for(exc, path)
            if translated is None:
                raise
            raise translated from exc
        # a lazy listing fetches further pages while it is consumed; a file handle from
        # openbin is iterable too but must be returned as it is
        if isinstance(result, Iterator) and not hasattr(result, "read"):
            return _translating_iterator(result, path)
        return result

    wrapper._translates_api_errors = True
    return wrapper


class RSpaceInfo(Info):
    """An ``Info`` with convenient access to the RSpace record it was built from."""

    @property
    def rspace(self) -> dict:
        return self.raw.get("rspace") or {}

    @property
    def global_id(self) -> Optional[str]:
        return self.rspace.get("globalId")

    #: Historical spelling, kept because the pre-2.8 Info classes exposed it as an attribute.
    globalId = global_id

    @property
    def rspace_name(self) -> Optional[str]:
        """The human-readable RSpace name (not the path segment)."""
        return self.rspace.get("name")


def to_epoch(value: Any) -> Optional[float]:
    """Convert an RSpace timestamp (ISO-8601 string, or epoch millis/seconds) to epoch seconds."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value) / 1000.0 if value > 1e11 else float(value)
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def make_info(name: str, is_dir: bool, raw: Optional[Mapping] = None, size: Optional[int] = None,
              created: Any = None, modified: Any = None,
              writable: Optional[bool] = None) -> RSpaceInfo:
    """Build an RSpaceInfo. ``name`` must be the entry's own path segment.

    ``writable`` fills the standard ``access`` namespace, for the entries where RSpace tells
    us something specific: an ELN document reports whether it is signed, which locks it.
    Leave it None where nothing is known, so that an absent ``access`` namespace means
    "unknown" rather than a guess. Note that it reflects only what the API reports: a record
    shared read-only with you is equally unwritable and looks no different from here.
    """
    details = {"type": int(ResourceType.directory if is_dir else ResourceType.file)}
    if size is not None:
        details["size"] = size
    created_epoch = to_epoch(created)
    if created_epoch is not None:
        details["created"] = created_epoch
    modified_epoch = to_epoch(modified)
    if modified_epoch is not None:
        details["modified"] = modified_epoch
    namespaces = {
        "basic": {"name": name, "is_dir": is_dir},
        "details": details,
        "rspace": dict(raw) if raw else {},
    }
    if writable is not None:
        executable = 0o111 if is_dir else 0o000  # a directory has to be traversable
        namespaces["access"] = {
            "permissions": Permissions(mode=0o444 | executable | (0o200 if writable else 0)).dump()
        }
    return RSpaceInfo(namespaces)


def with_name(info: RSpaceInfo, name: Text) -> RSpaceInfo:
    """The same Info under a different path segment."""
    raw = dict(info.raw)
    raw["basic"] = dict(raw.get("basic") or {}, name=name)
    return RSpaceInfo(raw)


@dataclass
class Target:
    """What a path addresses, as worked out by a branch's ``_resolve``.

    ``kind`` is the branch's own vocabulary (``record``, ``field``, ``document``, ``file``...),
    ``gid`` the global ID of the addressed record, ``parent_gid`` the record a field or file
    belongs to (an Inventory record, an ELN document), ``field_gid`` the field a file was
    reached through, and ``section`` the Inventory root section the path went through.
    """
    kind: str
    gid: Optional[str] = None
    parent_gid: Optional[str] = None
    field_gid: Optional[str] = None
    section: Optional[str] = None


def client_or_new(client, factory, server: Optional[str], api_key: Optional[str], what: str):
    """The client that was passed in, or a new one from ``server`` and ``api_key``."""
    if client is not None:
        return client
    if not server or not api_key:
        raise ValueError(f"{what} needs server and api_key, or a client")
    return factory(server, api_key)


def posture_meta(meta: Dict[Text, object], writable: bool, allow_delete: bool) -> Dict[Text, object]:
    """Read-only means nothing here can change, so a filesystem that may delete is not
    read-only even when it refuses uploads. The two flags are deliberately separate,
    which makes writable=False, allow_delete=True a reachable combination."""
    meta["read_only"] = not (writable or allow_delete)
    return meta


def stream_pages(client: ClientBase, first_page: Mapping, key: Text) -> Iterator[dict]:
    """
    Stream the records of a paginated RSpace response.

    ``first_page`` is the first response, ``key`` the name of the collection inside it
    ("records", "containers", "samples", ...). The next API page is fetched only when the
    consumer reaches it, so a caller that stops after a handful of entries (Galaxy passes
    its own limit and offset) never pays for the rest of the listing.
    """
    page = first_page
    while True:
        yield from page.get(key, [])
        if not any(link.get("rel") == "next" for link in page.get("_links") or []):
            return
        page = client.get_link_contents(page, "next")


class RSpaceFSBase(FS):
    """Common behaviour for all RSpace filesystems. Subclasses implement the RSpace calls."""

    #: How many resolved name lookups to remember before starting over. Deep trees browsed
    #: top-down reuse the same handful of entries, so a small bound is plenty.
    NAME_CACHE_LIMIT = 4096

    _meta = {
        "case_insensitive": False,
        "invalid_path_chars": "\0",
        "network": True,
        "read_only": True,
        "supports_rename": False,
        "unicode_paths": True,
    }

    def __init_subclass__(cls, **kwargs) -> None:
        super().__init_subclass__(**kwargs)
        # every subclass gets the translation on the methods it defines or overrides, so a new
        # branch cannot forget it
        for name in _TRANSLATED_METHODS:
            method = cls.__dict__.get(name)
            if method is not None:
                setattr(cls, name, translate_api_errors(method))

    def __init__(self, *, writable: bool = False, allow_delete: bool = False,
                 path_style: str = "name") -> None:
        super().__init__()
        if path_style not in paths.PATH_STYLES:
            raise ValueError(f"path_style must be one of {paths.PATH_STYLES}, got {path_style!r}")
        self.writable = writable
        self.allow_delete = allow_delete
        #: "name" -> segments look like 'Images'; "labelled" -> 'Images [GF12]'; "id" -> 'GF12'.
        #: See paths.py.
        self.path_style = path_style
        #: (parent path, segment) -> global ID, for segments written as a plain name. A name
        #: can only be resolved against its parent's listing, so without this every operation
        #: on a deep path would re-list every directory above it.
        self._name_cache: Dict[Tuple[Text, Text], Text] = {}

    def _segment(self, name, gid: str) -> str:
        """Path segment (and Info.name) for a record, in this filesystem's path style."""
        return paths.segment_for(self.path_style, name, gid)

    def _upload_target(self, path: Text):
        """
        Split an upload path into the container to put the file in and the name to give it.

        ``upload(path, file)`` means what PyFilesystem says it means: write this file object
        to the file at ``path``. So the last segment is the name of the file to create and its
        parent is the container (a Gallery folder, an Inventory record, a document field).
        The deprecated filesystems in ``rspace_client.eln.fs`` and
        ``rspace_client.inv.attachment_fs`` keep the older convention where ``path`` named the
        container itself.
        """
        name = paths.last_segment(path)
        if not name or paths.is_root(path):
            raise errors.FileExpected(path)
        return paths.parent_path(path), name

    @staticmethod
    def _upload_kwargs(name: Text) -> dict:
        """Extra keywords for the client's upload call: the name to store the file under,
        which is the last segment of the upload path. The deprecated shims return nothing
        here, because they name the file after the file object and because Galaxy's shipped
        file source replaces ``ELNClient.upload_file`` with a function that takes no
        ``filename`` keyword."""
        return {"filename": name}

    def getmeta(self, namespace: Text = "standard") -> Mapping[Text, object]:
        meta = dict(super().getmeta(namespace))
        return posture_meta(meta, self.writable, self.allow_delete) if namespace == "standard" else meta

    # ------------------------------------------------------------ write guard

    def _require_writable(self, path: Text) -> None:
        if not self.writable:
            raise errors.ResourceReadOnly(
                path, msg=f"{path!r}: this filesystem was opened read-only; pass writable=True to allow writes")

    def _require_delete(self, path: Text) -> None:
        if not self.allow_delete:
            raise errors.ResourceReadOnly(
                path, msg=f"{path!r}: deletion is disabled; pass allow_delete=True to allow it")

    # ------------------------------------------------------------ listing

    @translate_api_errors
    def scandir(self, path: Text, namespaces: Optional[Collection[Text]] = None,
                page: Optional[tuple] = None) -> Iterator[Info]:
        """Yield an Info per child from a single RSpace listing call (see ``_scan``)."""
        self.check()
        _path = self.validatepath(path)
        iter_info = self._listing(_path, namespaces or ())
        if page is not None:
            start, end = page
            iter_info = itertools.islice(iter_info, start, end)
        return iter_info

    @translate_api_errors
    def listdir(self, path: Text) -> List[Text]:
        return [info.name for info in self.scandir(path)]

    def _listing(self, path: Text, namespaces: Collection[Text]) -> Iterator[Info]:
        """``_scan`` with the guarantee that no two children share a path segment.

        RSpace lets siblings share a name, so under the ``name`` path style a plain listing
        could show the same segment twice, which would make one of the two unreachable and
        make a copy overwrite the other. The first record to use a name keeps it and every
        later one gains its global ID, which matches how ``_lookup`` resolves a bare name.
        The rule needs no lookahead, so listings stay lazy.
        """
        # _scan resolves the directory before returning its generator, so that a bad path
        # fails here rather than on first iteration; keep that by not making this a generator.
        children = self._scan(path, namespaces)
        return children if self.path_style != "name" else self._disambiguated(children)

    @staticmethod
    def _disambiguated(children: Iterator[Info]) -> Iterator[Info]:
        seen = set()
        for info in children:
            gid = (info.raw.get("rspace") or {}).get("globalId")
            if info.name in seen and gid:
                info = with_name(info, paths.disambiguated_segment(info.name, gid))
            seen.add(info.name)
            yield info

    #: ``Target.kind`` values that are files: listing one raises ``DirectoryExpected``.
    FILE_KINDS: Tuple[str, ...] = ()

    def _resolve(self, path: Text) -> Target:
        """What ``path`` addresses. Branches implement it with their own vocabulary."""
        raise NotImplementedError(f"{type(self).__name__} does not implement _resolve")

    def _children(self, target: Target) -> Iterator[Info]:
        """The entries inside a directory target, from one listing call where possible."""
        raise NotImplementedError(f"{type(self).__name__} does not implement _children")

    def _scan(self, path: Text, namespaces: Collection[Text]) -> Iterator[Info]:
        """This directory's children. Resolves eagerly so a bad path fails on the scandir
        call rather than on first iteration; ``listdir`` and ``scandir`` are both served
        from it."""
        target = self._resolve(path)
        if target.kind in self.FILE_KINDS:
            raise errors.DirectoryExpected(path)
        return self._children(target)

    def _gids(self, segments: List[Text], start: int = 0) -> Iterator[Tuple[int, Text]]:
        """``(index, global id)`` for each segment from ``start`` on. A segment carrying a
        global ID says what it addresses; a bare name is looked up in its parent's listing."""
        for index in range(start, len(segments)):
            gid, _ = paths.parse_segment(segments[index])
            if gid is None:
                gid = self._lookup("/" + "/".join(segments[:index]), segments[index])
            yield index, gid

    def _info(self, record: Mapping, is_dir: bool, gid: Optional[Text] = None,
              name: Optional[Text] = None, **extra: Any) -> RSpaceInfo:
        """The Info for an RSpace record, named after it in this filesystem's path style."""
        gid = gid or record["globalId"]
        return make_info(self._segment(record.get("name") if name is None else name, gid), is_dir,
                         raw=record, size=record.get("size"), created=record.get("created"),
                         modified=record.get("lastModified"), **extra)

    @staticmethod
    def _find_field(fields: Iterable[Mapping], field_gid: Text, owner: Text) -> dict:
        for field in fields:
            if field.get("globalId") == field_gid:
                return field
        raise errors.ResourceNotFound(f"{owner}/{field_gid}")

    def _is_empty(self, path: Text) -> bool:
        """True if the directory has no children, without listing all of them."""
        return next(iter(self.scandir(path)), None) is None

    # ------------------------------------------------------------ resolving a segment

    def _lookup(self, parent: Text, segment: Text) -> Text:
        """Global ID of the child of ``parent`` whose path segment is ``segment``.

        Only needed for a segment written as a plain name: one carrying a global ID says
        what it addresses. Costs one listing of the parent, remembered afterwards.
        """
        key = (parent, segment)
        cached = self._name_cache.get(key)
        if cached is not None:
            return cached
        for info in self._listing(parent, ()):
            gid = (info.raw.get("rspace") or {}).get("globalId")
            # match the marked and unmarked spellings, so a path stored before a document
            # was signed still resolves after it was
            if segment in (info.name, paths.unmarked(info.name)) and gid:
                if len(self._name_cache) >= self.NAME_CACHE_LIMIT:
                    self._name_cache.clear()
                self._name_cache[key] = gid
                return gid
        raise errors.ResourceNotFound(join(parent, segment))

    def _gid_at(self, path: Text) -> Text:
        """Global ID addressed by the last segment of ``path``, whichever style wrote it."""
        segment = paths.last_segment(path)
        gid, _ = paths.parse_segment(segment)
        return gid if gid is not None else self._lookup(paths.parent_path(path), segment)

    def clear_name_cache(self) -> None:
        """Forget resolved name lookups. Called after every change made through this
        filesystem; call it yourself if records are renamed elsewhere while it is open."""
        self._name_cache.clear()

    # ------------------------------------------------------------ files

    @translate_api_errors
    def openbin(self, path: Text, mode: Text = "r", buffering: int = -1, **options: Any) -> BinaryIO:
        """
        Conformance shim. In almost all cases prefer ``download`` / ``upload`` directly:
        they stream, and an uploaded file keeps the name of the source file object.
        Reads buffer the whole file; writes are sent when the returned file is closed.
        """
        _mode = Mode(mode)
        _mode.validate_bin()
        if _mode.reading and _mode.writing:
            raise errors.Unsupported("read/write mode")
        if _mode.appending:
            raise errors.Unsupported("appending mode")
        if _mode.exclusive:
            raise errors.Unsupported("exclusive mode")
        if _mode.truncate and not _mode.writing:
            raise errors.Unsupported("truncate mode")

        if _mode.reading:
            buffer = BytesIO()
            self.download(path, buffer)
            buffer.seek(0)
            return buffer

        if _mode.writing:
            self._require_writable(path)
            if not basename(path):
                raise errors.FileExpected(path)
            buffer = BytesIO()
            original_close = buffer.close
            done = False

            def upload_on_close() -> None:
                nonlocal done
                if done:  # closing twice must not re-upload, nor raise
                    return
                done = True
                buffer.seek(0)
                try:
                    self.upload(path, buffer)  # upload() resolves the container and the name
                finally:
                    original_close()

            buffer.close = upload_on_close  # type: ignore[method-assign]
            return buffer

        raise errors.Unsupported(f"mode {mode!r}")

    def _file_source(self, path: Text) -> Tuple[Text, Callable]:
        """``(numeric id, client download method)`` for the file at ``path``. Raises
        ``FileExpected`` for anything that is not a file. Branches implement it."""
        raise errors.Unsupported("download")

    def download(self, path: Text, file: BinaryIO, chunk_size: Optional[int] = None, **options: Any) -> None:
        numeric_id, fetch = self._file_source(self.validatepath(path))
        if chunk_size is not None:
            fetch(numeric_id, file, chunk_size)
        else:
            fetch(numeric_id, file)

    def upload(self, path: Text, file: BinaryIO, chunk_size: Optional[int] = None, **options: Any) -> None:
        raise errors.Unsupported("upload")

    def _upload_prelude(self, path: Text) -> Tuple[Text, Text, Text, Target]:
        """``(validated path, container path, file name, resolved container)`` for an upload."""
        _path = self.validatepath(path)
        container, name = self._upload_target(_path)
        return _path, container, name, self._resolve(container)

    # ------------------------------------------------------------ folder templates

    @staticmethod
    def _new_folder(_path: Text) -> Tuple[Text, Text]:
        """``(parent path, folder name)`` for makedir. 'New [GF1]' creates 'New', as does
        'New'; a bare global ID is refused because it names nothing to create."""
        segment = paths.last_segment(_path)
        gid, label = paths.parse_segment(segment)
        if gid is not None and label is None:
            raise errors.InvalidPath(_path, msg="makedir takes a folder name, not a global ID")
        return paths.parent_path(_path), label if gid is not None else segment

    def _create_folder(self, _path: Text, parent_path: Text, name: Text, siblings: Iterable[Mapping],
                       create: Callable[[], Mapping], folder_prefixes: Tuple[Text, ...],
                       recreate: bool) -> SubFS:
        """Create ``name`` under ``parent_path`` unless a folder of that name is already among
        ``siblings``. RSpace would happily make a second folder with the same name; the
        filesystem contract says to refuse instead (or to return the existing one)."""
        for record in siblings:
            if record.get("name") == name and record["globalId"][:2] in folder_prefixes:
                if recreate:
                    return SubFS(self, join(parent_path, self._segment(name, record["globalId"])))
                raise errors.DirectoryExists(_path)
        created = create()
        gid = created.get("globalId") or f"{folder_prefixes[0]}{created['id']}"
        self.clear_name_cache()
        return SubFS(self, join(parent_path, self._segment(name, gid)))

    def _remove_folder(self, _path: Text, folder_gid: Callable[[], Optional[Text]],
                       delete: Callable[[Text], Any], not_a_folder: errors.FSError) -> None:
        """Delete the empty folder at ``_path``. ``folder_gid`` returns its global ID, or None
        when the path is not a removable folder, in which case ``not_a_folder`` is raised."""
        if paths.is_root(_path):
            raise errors.RemoveRootError(_path)
        gid = folder_gid()
        if gid is None:
            raise not_a_folder
        if not self._is_empty(_path):
            raise errors.DirectoryNotEmpty(_path)
        delete(gid[2:])
        self.clear_name_cache()

    # ------------------------------------------------------------ mutations (defaults)

    def move(self, src_path: Text, dst_path: Text, overwrite: bool = False,
             preserve_time: bool = False) -> None:
        """A move is a copy followed by a remove, so check that the remove is allowed
        *before* uploading: otherwise the copy succeeds and the caller is left with an
        error and a duplicate the API may not be able to delete."""
        self._require_writable(dst_path)
        self._require_delete(src_path)
        super().move(src_path, dst_path, overwrite=overwrite, preserve_time=preserve_time)

    def makedir(self, path: Text, permissions=None, recreate: bool = False):
        raise errors.Unsupported("makedir", msg=f"{type(self).__name__} cannot create directories")

    def remove(self, path: Text) -> None:
        raise errors.Unsupported("remove", msg=f"{type(self).__name__} cannot delete files")

    def removedir(self, path: Text) -> None:
        raise errors.Unsupported("removedir", msg=f"{type(self).__name__} cannot delete directories")

    @translate_api_errors
    @writes
    def setinfo(self, path: Text, info: Mapping[Text, Mapping[Text, object]]) -> None:
        """RSpace owns its metadata. Timestamps are accepted and ignored, because that is
        what ``copy(..., preserve_time=True)`` and ``move`` send after a successful transfer
        and failing there would leave the copy in place and the caller with an error.
        Anything else is refused."""
        extra = {ns: {k for k in values if k not in ("accessed", "modified", "created")}
                 for ns, values in info.items() if ns == "details"}
        unsupported = [ns for ns in info if ns != "details"] + [k for ks in extra.values() for k in ks]
        if unsupported:
            raise errors.Unsupported(
                "setinfo", msg=f"RSpace metadata cannot be set through the filesystem: {unsupported}")
        self.getinfo(path)  # the path has to exist, as for any setinfo
