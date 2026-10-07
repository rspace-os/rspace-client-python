"""
Shared base class for the RSpace fsspec filesystems.

Provides, so that every branch (Gallery, Inventory, Workspace) behaves the same:

* a path style: ``name`` shows a record's own name, ``labelled`` shows ``Name [GID]``
  and ``id`` shows bare global IDs. A segment carrying a global ID resolves under
  every style, in one call; a *bare name* resolves only under ``name``, through
  ``_lookup``, which matches it against the parent's listing;
* a write posture: read-only by default, ``writable=True`` enables uploads and
  folder creation, ``allow_delete=True`` enables removals;
* ``entry`` dicts in fsspec's shape (``name`` is the full path without a leading
  slash, ``type`` is ``file`` or ``directory``, ``size``, ``mtime`` and ``created`` are
  epoch seconds) plus ``globalId``, ``rspace`` (the raw RSpace record) and, where RSpace
  tells us, ``writable``;
* ``ls``/``scandir``, which subclasses feed from a single listing call via ``_children``
  instead of one ``info`` request per child, and which keep the segments in a listing
  unique and self-addressing even when two records share a name (see ``_listing``);
* ``stream_pages``, which turns any paginated RSpace response into a lazy stream of
  records by following its ``next`` links only as far as the consumer reads;
* file I/O: reads buffer the whole file (RSpace serves no byte ranges), writes buffer
  until the file is closed or committed and upload in one request, which is what makes
  fsspec transactions work;
* error mapping: RSpace client exceptions become builtin ``OSError`` subclasses at every
  public method, so ``exists``, ``walk``, ``copy`` and Galaxy behave;
* a ``glob`` that understands the ``<dir>/*<text>*`` pattern Galaxy's search sends, with
  the escaping Galaxy applies, so that a segment carrying ``[GL83]`` can be found.
"""
from __future__ import annotations

import errno
import functools
import io
import re
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import (Any, BinaryIO, Callable, Dict, Iterable, Iterator, List, Mapping, Optional,
                    Tuple)

from fsspec.spec import AbstractBufferedFile, AbstractFileSystem

from rspace_client.client_base import ClientBase
from rspace_client.exceptions import ApiError, AuthenticationError, RSpaceConnectionError

from . import paths


# ------------------------------------------------------------------ errors
#
# fsspec callers (``exists``, ``walk``, ``copy``, Galaxy's file source) expect ``OSError``
# subclasses: ``FileNotFoundError`` for a missing path, ``PermissionError`` for a refusal,
# ``FileExistsError`` for a clash. The RSpace clients raise their own exceptions, so every
# public filesystem method translates them at the boundary, once, here.


class RemoteApiError(OSError):
    """An RSpace API refusal that is neither "not found" nor "not allowed": a wrong Gallery
    section (422), a refused link (409), a bad request (400). Carries the server's own
    explanation in ``str()`` and the original exception as ``api_error``."""

    def __init__(self, path: str, exc: Exception) -> None:
        super().__init__(errno.EIO, f"{path!r}: {exc}", path)
        self.api_error = exc
        self.status = getattr(exc, "response_status_code", None)


class ReadOnlyError(PermissionError):
    """A write was refused because of the filesystem's posture, not by the server."""


def os_error_for(exc: Exception, path: str) -> Optional[OSError]:
    """The ``OSError`` that stands for a client exception, or None to re-raise as it is."""
    if getattr(exc, "fs_passthrough", False):  # e.g. GallerySectionMismatch: already explained
        return None
    if isinstance(exc, RSpaceConnectionError):
        return ConnectionError(f"{path!r}: {exc}")
    if isinstance(exc, AuthenticationError):
        return PermissionError(errno.EACCES, f"{path!r}: {exc}", path)
    status = getattr(exc, "response_status_code", None)
    if status == 404:
        return FileNotFoundError(errno.ENOENT, f"{path!r}: {exc}", path)
    if status in (401, 403):
        return PermissionError(errno.EACCES, f"{path!r}: {exc}", path)
    if status is not None and status >= 500:
        return ConnectionError(f"{path!r}: {exc}")
    if isinstance(exc, ApiError):
        return RemoteApiError(path, exc)
    return None


#: Public methods whose first argument is a path and which may call the server.
_TRANSLATED_METHODS = ("ls", "scandir", "info", "cat_file", "get_file", "put_file", "_open",
                       "download_fileobj", "upload_fileobj", "mkdir", "makedirs", "rmdir",
                       "rm_file", "link", "glob", "cp_file", "mv", "created", "modified")


def _translating_iterator(iterator: Iterator, path: str) -> Iterator:
    try:
        yield from iterator
    except (ApiError, AuthenticationError, RSpaceConnectionError) as exc:
        translated = os_error_for(exc, path)
        if translated is None:
            raise
        raise translated from exc


def translate_api_errors(method):
    """Wrap a filesystem method so RSpace client errors surface as ``OSError``."""
    if getattr(method, "_translates_api_errors", False):
        return method

    @functools.wraps(method)
    def wrapper(self, path, *args, **kwargs):
        try:
            result = method(self, path, *args, **kwargs)
        except (ApiError, AuthenticationError, RSpaceConnectionError) as exc:
            translated = os_error_for(exc, str(path))
            if translated is None:
                raise
            raise translated from exc
        # a lazy listing fetches further pages while it is consumed; a file handle is
        # iterable too but must be returned as it is
        if isinstance(result, Iterator) and not hasattr(result, "read"):
            return _translating_iterator(result, str(path))
        return result

    wrapper._translates_api_errors = True
    return wrapper


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


# ------------------------------------------------------------------ entries


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


def make_entry(segment: str, is_dir: bool, raw: Optional[Mapping] = None, size: Optional[int] = None,
               created: Any = None, modified: Any = None, writable: Optional[bool] = None) -> dict:
    """Build an entry dict. ``segment`` is the entry's own path segment; ``ls`` prefixes the
    parent path later.

    ``writable`` is set only where RSpace tells us something specific (a signed ELN document
    is locked). Left None, the key is absent, which means "unknown" rather than a guess: a
    record shared read-only with you is equally unwritable and looks no different from here.
    """
    entry: Dict[str, Any] = {
        "name": segment,
        "type": "directory" if is_dir else "file",
        "size": size,
        # Galaxy and most fsspec consumers read mtime; RSpace files carry no lastModified,
        # so created stands in for it there
        "mtime": to_epoch(modified) if modified is not None else to_epoch(created),
        "created": to_epoch(created),
        "globalId": (raw or {}).get("globalId"),
        "rspace": dict(raw) if raw else {},
    }
    if writable is not None:
        entry["writable"] = writable
    return entry


def rspace_name(entry: Mapping) -> Optional[str]:
    """The human-readable RSpace name of an entry (not its path segment)."""
    return (entry.get("rspace") or {}).get("name")


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


def stream_pages(client: ClientBase, first_page: Mapping, key: str) -> Iterator[dict]:
    """
    Stream the records of a paginated RSpace response.

    ``first_page`` is the first response, ``key`` the name of the collection inside it
    ("records", "containers", "samples", ...). The next API page is fetched only when the
    consumer reaches it, so a caller that stops after a handful of entries never pays for
    the rest of the listing.
    """
    page = first_page
    while True:
        yield from page.get(key, [])
        if not any(link.get("rel") == "next" for link in page.get("_links") or []):
            return
        page = client.get_link_contents(page, "next")


# ------------------------------------------------------------------ files


class RSpaceWriteFile(AbstractBufferedFile):
    """A file opened for writing: everything is buffered and sent in one request when the
    file is closed (autocommit) or when the surrounding transaction commits. RSpace takes
    one multipart body per upload, so there is nothing to send chunk by chunk."""

    def _initiate_upload(self) -> None:
        pass

    def _upload_chunk(self, final: bool = False) -> bool:
        if final and self.autocommit:
            self._send()
        return False  # keep the buffer; one body per upload

    def commit(self) -> None:
        self._send()

    def discard(self) -> None:
        self.buffer = io.BytesIO()

    def _send(self) -> None:
        self.buffer.seek(0)
        self.fs.upload_fileobj(self.path, self.buffer)


class RSpaceFSBase(AbstractFileSystem):
    """Common behaviour for all RSpace filesystems. Subclasses implement the RSpace calls.

    Paths are fsspec paths: no protocol, no leading slash, the root is ``""``.
    """

    #: Instances hold an API key: never keep them in fsspec's process-wide instance cache.
    cachable = False
    root_marker = ""
    #: How many resolved name lookups to remember before starting over. Deep trees browsed
    #: top-down reuse the same handful of entries, so a small bound is plenty.
    NAME_CACHE_LIMIT = 4096
    #: ``Target.kind`` values that are files: listing one raises ``NotADirectoryError``.
    FILE_KINDS: Tuple[str, ...] = ()
    #: False where the RSpace API cannot delete a file (the Gallery): a move is then refused
    #: before anything is copied, since the second half could never happen.
    CAN_DELETE_FILES = True

    def __init_subclass__(cls, **kwargs) -> None:
        super().__init_subclass__(**kwargs)
        # every subclass gets the translation on the methods it defines or overrides, so a new
        # branch cannot forget it
        for name in _TRANSLATED_METHODS:
            method = cls.__dict__.get(name)
            if method is not None:
                setattr(cls, name, translate_api_errors(method))

    def __init__(self, *, writable: bool = False, allow_delete: bool = False,
                 path_style: str = "name", **storage_options: Any) -> None:
        # fsspec caches directory listings by default and never expires them; this
        # filesystem's own name cache is cleared on every write, so leave listings uncached
        # unless the caller (Galaxy's cache options, say) asks for them
        storage_options.setdefault("use_listings_cache", False)
        super().__init__(**storage_options)
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
        self._name_cache: Dict[Tuple[str, str], str] = {}
        #: True while a listing is read only to resolve a name or to test for emptiness:
        #: branches skip per-entry extras (the Gallery's size fetches) that nobody will see.
        self._names_only = False

    @contextmanager
    def _resolving(self):
        previous = self._names_only
        self._names_only = True
        try:
            yield
        finally:
            self._names_only = previous

    # ------------------------------------------------------------ paths

    @classmethod
    def _strip_protocol(cls, path):
        if isinstance(path, list):
            return [cls._strip_protocol(p) for p in path]
        path = super()._strip_protocol(path)
        return path.strip("/")

    @staticmethod
    def _join(parent: str, segment: str) -> str:
        return f"{parent}/{segment}" if parent else segment

    def _segment(self, name, gid: str) -> str:
        """Path segment for a record, in this filesystem's path style."""
        return paths.segment_for(self.path_style, name, gid)

    def _upload_target(self, path: str) -> Tuple[str, str]:
        """Split an upload path into the container to put the file in and the name to give
        it: the last segment is the name of the file to create and its parent is the
        container (a Gallery folder, an Inventory record, a document field)."""
        name = paths.last_segment(path)
        if not name or paths.is_root(path):
            raise IsADirectoryError(errno.EISDIR, f"{path!r}: a file path is needed to upload to", path)
        return self._parent(path), name

    @staticmethod
    def _upload_kwargs(name: str) -> dict:
        """Extra keywords for the client's upload call: the name to store the file under."""
        return {"filename": name}

    # ------------------------------------------------------------ write guard

    def _require_writable(self, path: str) -> None:
        if not self.writable:
            raise ReadOnlyError(
                errno.EROFS, f"{path!r}: this filesystem was opened read-only; pass writable=True "
                             f"to allow writes", str(path))

    def _require_delete(self, path: str) -> None:
        if not self.allow_delete:
            raise ReadOnlyError(
                errno.EROFS, f"{path!r}: deletion is disabled; pass allow_delete=True to allow it", str(path))

    @property
    def read_only(self) -> bool:
        """Read-only means nothing here can change, so a filesystem that may delete is not
        read-only even when it refuses uploads. The two flags are deliberately separate."""
        return not (self.writable or self.allow_delete)

    # ------------------------------------------------------------ listing

    def scandir(self, path: str) -> Iterator[dict]:
        """Yield an entry per child from a single RSpace listing call, lazily: a section or
        folder with thousands of records is fetched a page at a time as the iterator is
        consumed. ``ls`` is this, collected into a list."""
        path = self._strip_protocol(path)
        return self._listing(path)

    def ls(self, path: str, detail: bool = True, refresh: bool = False, **kwargs) -> list:
        path = self._strip_protocol(path)
        out = None if refresh else self.dircache.get(path)
        if out is None:
            # the directory is resolved before the list is built, so a bad path fails here
            out = list(self._listing(path))
            if self.dircache.use_listings_cache:
                self.dircache[path] = out
        return out if detail else [entry["name"] for entry in out]

    def _listing(self, path: str) -> Iterator[dict]:
        """``_children`` with full names and the guarantee that no two children share a
        segment and that every segment addresses the record it shows.

        RSpace lets siblings share a name, so under the ``name`` path style a plain listing
        could show the same segment twice, which would make one of the two unreachable. The
        first record to use a name keeps it and every later one gains its global ID before
        the extension (``data [GL112].csv``), which matches how ``_lookup`` resolves a bare
        name. A name that itself parses as an address (``report [GL111].txt``) is given its
        real ID the same way, in ``paths.segment_for``, so that a consumer which stores the
        segment and resolves it later (Galaxy stores URIs) always gets the record it saw.
        The rule needs no lookahead, so listings stay lazy.
        """
        # _children resolves the directory before returning its generator, so that a bad
        # path fails on the call rather than on first iteration; keep that by not making
        # this a generator
        target = self._resolve(path)
        if target.kind in self.FILE_KINDS:
            raise NotADirectoryError(errno.ENOTDIR, f"{path!r} is a file", path)
        children = self._children(target)
        return self._prefixed(path, self._disambiguated(children) if self.path_style == "name" else children)

    @staticmethod
    def _prefixed(parent: str, children: Iterator[dict]) -> Iterator[dict]:
        for entry in children:
            entry["name"] = f"{parent}/{entry['name']}" if parent else entry["name"]
            yield entry

    @staticmethod
    def _disambiguated(children: Iterator[dict]) -> Iterator[dict]:
        seen = set()
        for entry in children:
            gid = entry.get("globalId")
            if entry["name"] in seen and gid:
                entry["name"] = paths.disambiguated_segment(entry["name"], gid)
            seen.add(entry["name"])
            yield entry

    def _resolve(self, path: str) -> Target:
        """What ``path`` addresses. Branches implement it with their own vocabulary."""
        raise NotImplementedError(f"{type(self).__name__} does not implement _resolve")

    def _children(self, target: Target) -> Iterator[dict]:
        """The entries inside a directory target, with segment names, from one listing call
        where possible."""
        raise NotImplementedError(f"{type(self).__name__} does not implement _children")

    def _gids(self, segments: List[str], start: int = 0) -> Iterator[Tuple[int, str]]:
        """``(index, global id)`` for each segment from ``start`` on. A segment carrying a
        global ID says what it addresses; a bare name is looked up in its parent's listing."""
        for index in range(start, len(segments)):
            gid, _ = paths.parse_segment(segments[index])
            if gid is None:
                gid = self._lookup("/".join(segments[:index]), segments[index])
            yield index, gid

    def _entry(self, record: Mapping, is_dir: bool, gid: Optional[str] = None,
               name: Optional[str] = None, **extra: Any) -> dict:
        """The entry for an RSpace record, named after it in this filesystem's path style."""
        gid = gid or record["globalId"]
        return make_entry(self._segment(record.get("name") if name is None else name, gid), is_dir,
                          raw=record, size=record.get("size"), created=record.get("created"),
                          modified=record.get("lastModified"), **extra)

    @staticmethod
    def _find_field(fields: Iterable[Mapping], field_gid: str, owner: str) -> dict:
        for field in fields:
            if field.get("globalId") == field_gid:
                return field
        raise FileNotFoundError(errno.ENOENT, f"no field {field_gid} on {owner}", f"{owner}/{field_gid}")

    def _is_empty(self, path: str) -> bool:
        """True if the directory has no children, without listing all of them."""
        with self._resolving():
            return next(iter(self._listing(path)), None) is None

    # ------------------------------------------------------------ resolving a segment

    def _lookup(self, parent: str, segment: str) -> str:
        """Global ID of the child of ``parent`` whose path segment is ``segment``.

        Only needed for a segment written as a plain name: one carrying a global ID says
        what it addresses. Costs one listing of the parent, remembered afterwards.
        """
        key = (parent, segment)
        cached = self._name_cache.get(key)
        if cached is not None:
            return cached
        # the listing is lazy, so it must be consumed inside the resolving context for the
        # branches to see the flag
        with self._resolving():
            for entry in self._listing(parent):
                own = paths.last_segment(entry["name"])
                gid = entry.get("globalId")
                # match the marked and unmarked spellings, so a path stored before a document
                # was signed still resolves after it was
                if segment in (own, paths.unmarked(own)) and gid:
                    if len(self._name_cache) >= self.NAME_CACHE_LIMIT:
                        self._name_cache.clear()
                    self._name_cache[key] = gid
                    return gid
        raise FileNotFoundError(errno.ENOENT, f"{self._join(parent, segment)!r} not found",
                                self._join(parent, segment))

    def _gid_at(self, path: str) -> str:
        """Global ID addressed by the last segment of ``path``, whichever style wrote it."""
        segment = paths.last_segment(path)
        gid, _ = paths.parse_segment(segment)
        return gid if gid is not None else self._lookup(self._parent(path), segment)

    def clear_name_cache(self) -> None:
        """Forget resolved name lookups. Called after every change made through this
        filesystem; call it yourself if records are renamed elsewhere while it is open."""
        self._name_cache.clear()

    def invalidate_cache(self, path: Optional[str] = None) -> None:
        """Drop cached listings (fsspec's) and resolved names (ours).

        fsspec's default does nothing to the listings cache, so a write through this
        filesystem would otherwise leave a cached listing showing the old state. Writes are
        rare next to reads, so everything is dropped rather than just the paths involved.
        """
        super().invalidate_cache(path)
        self.dircache.clear()
        self.clear_name_cache()

    # ------------------------------------------------------------ info

    def info(self, path: str, **kwargs) -> dict:
        path = self._strip_protocol(path)
        entry = self._info_of(path, self._resolve(path))
        entry["name"] = path
        return entry

    def _info_of(self, path: str, target: Target) -> dict:
        """The entry for a resolved path. Branches implement it."""
        raise NotImplementedError(f"{type(self).__name__} does not implement _info_of")

    def created(self, path: str) -> Optional[datetime]:
        stamp = self.info(path).get("created")
        return datetime.fromtimestamp(stamp, tz=timezone.utc) if stamp is not None else None

    def modified(self, path: str) -> Optional[datetime]:
        stamp = self.info(path).get("mtime")
        return datetime.fromtimestamp(stamp, tz=timezone.utc) if stamp is not None else None

    # ------------------------------------------------------------ search

    _GALAXY_SEARCH = re.compile(r"^(?P<dir>.*?)/?\*(?P<text>.*)\*$", re.S)

    def glob(self, path: str, maxdepth: Optional[int] = None, **kwargs):
        """fsspec glob, with one special case: the ``<dir>/*<text>*`` pattern a search box
        sends (Galaxy builds exactly this) is answered by one listing of ``<dir>`` and a
        case-insensitive substring match on the last segment, in listing order. fsspec's
        own glob treats ``[`` as a character class and ignores the backslash Galaxy escapes
        it with, so a segment carrying ``[GL83]`` could never be found that way."""
        path = self._strip_protocol(path)
        match = self._GALAXY_SEARCH.match(path)
        text = match.group("text") if match else None
        if (match and "**" not in path and maxdepth in (None, 1)
                and not any(c in text.replace("\\", "") for c in "*?/")):
            needle = re.sub(r"\\(.)", r"\1", text).lower()
            found = {entry["name"]: entry for entry in self._listing(match.group("dir"))
                     if needle in paths.last_segment(entry["name"]).lower()}
            return found if kwargs.get("detail") else list(found)
        return super().glob(path, maxdepth=maxdepth, **kwargs)

    # ------------------------------------------------------------ files

    def _file_source(self, path: str) -> Tuple[str, Callable]:
        """``(numeric id, client download method)`` for the file at ``path``. Raises
        ``IsADirectoryError`` for anything that is not a file. Branches implement it."""
        raise NotImplementedError(f"{type(self).__name__} does not implement _file_source")

    def download_fileobj(self, path: str, file: BinaryIO, chunk_size: Optional[int] = None) -> None:
        """Stream the file at ``path`` into the open binary ``file``."""
        numeric_id, fetch = self._file_source(self._strip_protocol(path))
        if chunk_size is not None:
            fetch(numeric_id, file, chunk_size)
        else:
            fetch(numeric_id, file)

    def upload_fileobj(self, path: str, file: BinaryIO, **options: Any):
        """Write the open binary ``file`` to the file at ``path``: the last segment is the name
        to give it and its parent is the container to put it in. Branches implement it."""
        raise NotImplementedError(f"{type(self).__name__} cannot upload")

    def cat_file(self, path: str, start: Optional[int] = None, end: Optional[int] = None, **kwargs) -> bytes:
        buffer = io.BytesIO()
        self.download_fileobj(path, buffer)
        data = buffer.getvalue()
        return data[start:end] if (start is not None or end is not None) else data

    def get_file(self, rpath: str, lpath, callback=None, outfile=None, **kwargs) -> None:
        """Download straight into the local file, without the whole-file buffer ``open`` needs."""
        if isinstance(lpath, (str, bytes)) or hasattr(lpath, "__fspath__"):
            if self.isdir(rpath):
                import os
                os.makedirs(lpath, exist_ok=True)
                return
            with open(lpath, "wb") as handle:
                self.download_fileobj(rpath, handle)
        else:
            self.download_fileobj(rpath, lpath)

    def put_file(self, lpath, rpath: str, callback=None, mode: str = "overwrite", **kwargs) -> None:
        """Upload the local file as the RSpace file at ``rpath``."""
        import os
        if os.path.isdir(lpath):
            # fsspec's put() hands directories through put_file as well, and relies on the
            # backend to create them before their files arrive
            self.makedirs(rpath, exist_ok=True)
            return
        with open(lpath, "rb") as handle:
            self.upload_fileobj(rpath, handle, **kwargs)

    def _open(self, path: str, mode: str = "rb", block_size=None, autocommit: bool = True,
              cache_options=None, **kwargs):
        """Reads buffer the whole file (RSpace serves no byte ranges). Writes buffer until the
        file is closed, or until the transaction commits, and upload in one request."""
        path = self._strip_protocol(path)
        if mode in ("rb", "r"):
            return io.BytesIO(self.cat_file(path))
        if mode in ("wb", "xb", "w", "x"):
            self._require_writable(path)
            if not paths.last_segment(path):
                raise IsADirectoryError(errno.EISDIR, f"{path!r} is a directory", path)
            if mode.startswith("x") and self.exists(path):
                raise FileExistsError(errno.EEXIST, f"{path!r} exists", path)
            return RSpaceWriteFile(self, path, mode="wb", block_size=2 ** 62, autocommit=autocommit)
        raise ValueError(f"mode {mode!r} is not supported; use 'rb' or 'wb'")

    # ------------------------------------------------------------ folders (templates)

    @staticmethod
    def _new_folder(path: str) -> Tuple[str, str]:
        """``(parent path, folder name)`` for mkdir. 'New [GF1]' creates 'New', as does
        'New'; a bare global ID is refused because it names nothing to create."""
        segment = paths.last_segment(path)
        gid, label = paths.parse_segment(segment)
        if gid is not None and label is None:
            raise ValueError(f"{path!r}: mkdir takes a folder name, not a global ID")
        return RSpaceFSBase._parent(path), label if gid is not None else segment

    def _create_folder(self, path: str, name: str, siblings: Iterable[Mapping],
                       create: Callable[[], Mapping], folder_prefixes: Tuple[str, ...],
                       exist_ok: bool) -> str:
        """Create ``name`` unless a folder of that name is already among ``siblings``. RSpace
        would happily make a second folder with the same name; the filesystem contract says
        to refuse instead (or, with ``exist_ok``, to return the existing one). Returns the
        path of the folder, in this filesystem's path style."""
        parent = self._parent(path)
        for record in siblings:
            if record.get("name") == name and record["globalId"][:2] in folder_prefixes:
                if exist_ok:
                    return self._join(parent, self._segment(name, record["globalId"]))
                raise FileExistsError(errno.EEXIST, f"{path!r} exists", path)
        created = create()
        gid = created.get("globalId") or f"{folder_prefixes[0]}{created['id']}"
        self.invalidate_cache()
        return self._join(parent, self._segment(name, gid))

    def _remove_folder(self, path: str, folder_gid: Optional[str], delete: Callable[[str], Any],
                       not_a_folder: Exception) -> None:
        """Delete the empty folder at ``path``. ``folder_gid`` is its global ID, or None when
        the path is not a removable folder, in which case ``not_a_folder`` is raised."""
        if paths.is_root(path):
            raise PermissionError(errno.EPERM, "the root cannot be removed", path)
        if folder_gid is None:
            raise not_a_folder
        if not self._is_empty(path):
            raise OSError(errno.ENOTEMPTY, f"{path!r} is not empty", path)
        delete(folder_gid[2:])
        self.invalidate_cache()

    # ------------------------------------------------------------ mutations (defaults)

    def mkdir(self, path: str, create_parents: bool = True, **kwargs) -> None:
        raise NotImplementedError(f"{type(self).__name__} cannot create directories")

    def makedirs(self, path: str, exist_ok: bool = False) -> None:
        """Only the last segment is created; RSpace folders are not made in bulk here."""
        path = self._strip_protocol(path)
        if exist_ok and self.exists(path):
            if not self.isdir(path):
                raise FileExistsError(errno.EEXIST, f"{path!r} exists and is not a directory", path)
            return
        self.mkdir(path, create_parents=False, exist_ok=exist_ok)

    def rmdir(self, path: str) -> None:
        raise NotImplementedError(f"{type(self).__name__} cannot delete directories")

    def rm_file(self, path: str) -> None:
        raise NotImplementedError(f"{type(self).__name__} cannot delete files")

    def rm(self, path, recursive: bool = False, maxdepth: Optional[int] = None) -> None:
        """Remove files and empty directories. Recursive removal is refused: RSpace records
        are not something a filesystem should delete wholesale."""
        if recursive:
            raise NotImplementedError("recursive removal is not supported on RSpace")
        for one in ([path] if isinstance(path, str) else path):
            one = self._strip_protocol(one)
            if self.isdir(one):
                self.rmdir(one)
            else:
                self.rm_file(one)

    def cp_file(self, path1: str, path2: str, **kwargs) -> None:
        """Copy a file within this filesystem by downloading and uploading it."""
        path1, path2 = self._strip_protocol(path1), self._strip_protocol(path2)
        self._require_writable(path2)
        self.upload_fileobj(path2, io.BytesIO(self.cat_file(path1)))

    def mv(self, path1: str, path2: str, recursive: bool = False, maxdepth: Optional[int] = None,
           **kwargs) -> None:
        """A move is a copy followed by a remove, so check that the remove is allowed
        *before* uploading: otherwise the copy succeeds and the caller is left with an
        error and a duplicate the API may not be able to delete."""
        self._require_writable(path2)
        self._require_delete(path1)
        if not self.CAN_DELETE_FILES:
            raise NotImplementedError(
                f"{type(self).__name__} cannot move files: the RSpace API cannot delete the source")
        if recursive:
            raise NotImplementedError("recursive move is not supported on RSpace")
        self.cp_file(path1, path2)
        self.rm_file(path1)


# ``__init_subclass__`` only sees subclasses; the methods the base defines itself (``ls``,
# ``info``, ``cat_file``...) are translated here, once, so a branch that inherits them
# unchanged still raises ``OSError`` rather than a client exception.
for _name in _TRANSLATED_METHODS:
    if _name in RSpaceFSBase.__dict__:
        setattr(RSpaceFSBase, _name, translate_api_errors(RSpaceFSBase.__dict__[_name]))
del _name
