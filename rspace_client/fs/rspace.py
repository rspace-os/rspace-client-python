"""
One filesystem across RSpace.

``RSpaceFilesystem`` is an fsspec filesystem with the RSpace branches mounted under fixed,
human-readable top-level names, so that ``ls("")`` tells a user what worlds exist:

    gallery      the Gallery (GalleryFilesystem)
    inventory    benches, Containers, Samples, Templates; every record is a folder (InventoryFilesystem)
    workspace    ELN folders, notebooks, documents and their fields (WorkspaceFilesystem)

``mounts`` chooses which of those to expose, for a caller that only wants one part of RSpace
(a Galaxy file source, say, where the person configuring it picks what their group needs).
The names and the paths below them do not change, so narrowing the set later does not
invalidate paths to the branches that remain.

All branches share one ``ELNClient`` and one ``InventoryClient``, and one write
posture: read-only by default, ``writable=True`` for uploads and folder creation,
``allow_delete=True`` for removals. Paths are the records' own names by default
(``gallery/Images/microscope.png``); pass ``path_style="labelled"`` for ``Name [GID]``
segments or ``path_style="id"`` for bare global IDs. A segment carrying a global ID is
accepted whatever the style. The top level itself is fixed and cannot be written to.

    fs = RSpaceFilesystem("https://rspace.example.org", api_key)
    fs.ls("", detail=False)                 # ['gallery', 'inventory', 'workspace']
    fs.get_file("gallery/Images/microscope.png", "out.png")

or, with ``RSPACE_API_KEY`` in the environment:

    fsspec.filesystem("rspace", server="https://rspace.example.org")
    fsspec.open("rspace://rspace.example.org/gallery/Images/microscope.png")
    UPath("rspace://rspace.example.org/gallery")

The URL never carries the API key. The host is taken from the URL and the key only from
the ``RSPACE_API_KEY`` environment variable; a URL with ``user:password@`` is rejected and
plain http is accepted for loopback hosts only, because a URL is often supplied by someone
other than the person whose environment it is opened in.
"""
from __future__ import annotations

import errno
import io
import os
from typing import Any, Collection, Dict, Iterator, Optional, Tuple
from urllib.parse import parse_qs, urlsplit

from fsspec.spec import AbstractFileSystem

from rspace_client.eln import eln
from rspace_client.inv import inv

from . import paths
from .base import (ReadOnlyError, RSpaceFSBase, make_entry, translate_api_errors, _TRANSLATED_METHODS)
from .gallery import ON_MISMATCH_RAISE, GalleryFilesystem
from .inventory import InventoryFilesystem
from .workspace import WorkspaceFilesystem

MOUNTS = ("gallery", "inventory", "workspace")
KEY_ENV = "RSPACE_API_KEY"
_TRUE = ("1", "true", "yes", "on")
#: The only hosts plain http may be used with: a development server on this machine. Over
#: the network the key would travel in clear text.
LOOPBACK_HOSTS = ("localhost", "127.0.0.1", "::1")


def _flag(params: Dict[str, Any], name: str) -> bool:
    value = params.get(name, "")
    if isinstance(value, list):
        value = value[-1] if value else ""
    return str(value).lower() in _TRUE


class RSpaceFilesystem(AbstractFileSystem):
    """Target: the first segment names a branch; the rest is that branch's path."""

    protocol = ("rspace",)
    root_marker = ""
    cachable = False

    def __init_subclass__(cls, **kwargs) -> None:
        super().__init_subclass__(**kwargs)
        for name in _TRANSLATED_METHODS:
            method = cls.__dict__.get(name)
            if method is not None:
                setattr(cls, name, translate_api_errors(method))

    def __init__(self, server: Optional[str] = None, api_key: Optional[str] = None, *,
                 eln_client: Optional[eln.ELNClient] = None,
                 inv_client: Optional[inv.InventoryClient] = None,
                 writable: bool = False, allow_delete: bool = False,
                 path_style: str = "name", on_mismatch: str = ON_MISMATCH_RAISE,
                 mounts: Collection[str] = MOUNTS, fetch_sizes: bool = True,
                 **storage_options: Any) -> None:
        storage_options.setdefault("use_listings_cache", False)
        super().__init__(**storage_options)
        # keep the canonical order however they were listed, so ls('') is stable
        chosen = tuple(name for name in MOUNTS if name in set(mounts))
        unknown = sorted(set(mounts) - set(MOUNTS))
        if unknown:
            raise ValueError(f"unknown mounts {unknown}, choose from {list(MOUNTS)}")
        if not chosen:
            raise ValueError(f"mounts cannot be empty, choose from {list(MOUNTS)}")
        if path_style not in paths.PATH_STYLES:
            raise ValueError(f"path_style must be one of {paths.PATH_STYLES}, got {path_style!r}")
        if api_key is None and server and eln_client is None:
            # the one place the environment is consulted, so that a URL cannot name the
            # variable that leaves the machine
            api_key = os.environ.get(KEY_ENV)
            if not api_key:
                raise ValueError(f"no API key: pass api_key= or set the {KEY_ENV} environment variable")
        # Only the clients the chosen branches use are required: every branch needs the ELN
        # client (Inventory uploads go through the Gallery), Inventory alone needs the other.
        can_build = bool(server and api_key)
        if eln_client is None and not can_build:
            raise ValueError("RSpaceFilesystem needs server and api_key, or an eln_client")
        if "inventory" in chosen and inv_client is None and not can_build:
            raise ValueError("RSpaceFilesystem needs server and api_key, or an inv_client, to mount inventory")
        #: which RSpace branches this filesystem exposes, in listing order
        self.mount_names = chosen
        self.server = server
        self.writable = writable
        self.allow_delete = allow_delete
        self.path_style = path_style
        self.eln_client = eln_client or eln.ELNClient(server, api_key)
        if inv_client is None and "inventory" in chosen:
            inv_client = inv.InventoryClient(server, api_key)
        #: None when inventory is not mounted and no client was given
        self.inv_client = inv_client
        #: what to do when a file is uploaded to a Gallery folder whose media-type section
        #: does not accept it: "raise" (default) or "reroute" (let RSpace place it correctly).
        #: A single upload can override it with ``upload_fileobj(..., on_mismatch=...)``.
        self.on_mismatch = on_mismatch
        posture = dict(writable=writable, allow_delete=allow_delete, path_style=path_style,
                       use_listings_cache=self.dircache.use_listings_cache,
                       listings_expiry_time=self.dircache.listings_expiry_time,
                       max_paths=self.dircache.max_paths)
        builders = {
            "gallery": lambda: GalleryFilesystem(
                eln_client=self.eln_client, on_mismatch=on_mismatch, fetch_sizes=fetch_sizes, **posture),
            "inventory": lambda: InventoryFilesystem(
                inv_client=self.inv_client, eln_client=self.eln_client, **posture),
            "workspace": lambda: WorkspaceFilesystem(eln_client=self.eln_client, **posture),
        }
        #: each branch, or None when it was not mounted
        self.gallery: Optional[GalleryFilesystem] = None
        self.inventory: Optional[InventoryFilesystem] = None
        self.workspace: Optional[WorkspaceFilesystem] = None
        self.branches: Dict[str, RSpaceFSBase] = {}
        for name in self.mount_names:
            branch = builders[name]()
            setattr(self, name, branch)
            self.branches[name] = branch

    def __repr__(self) -> str:
        return f"RSpaceFilesystem({self.server!r}, mounts={list(self.mount_names)}, writable={self.writable})"

    # ------------------------------------------------------------ URLs

    @classmethod
    def _strip_protocol(cls, path) -> str:
        """``rspace://host/gallery/Images`` -> ``gallery/Images``. The host is a connection
        parameter (see ``_get_kwargs_from_urls``), not part of the path."""
        if isinstance(path, list):
            return [cls._strip_protocol(p) for p in path]
        path = super()._strip_protocol(path)
        if isinstance(path, str) and (path.startswith("http://") or path.startswith("https://")):
            return ""  # a bare URL after fsspec removed the protocol: nothing but a host
        # after fsspec removed 'rspace://' the first segment is the host when the original
        # string was a URL; fsspec hands us 'host/gallery/...' in that case
        return path.strip("/")

    @staticmethod
    def _get_kwargs_from_urls(url: str) -> Dict[str, Any]:
        """Connection options from ``rspace://host[:port]/path?writable=1&scheme=http``."""
        parts = urlsplit(url)
        if parts.scheme != "rspace":
            return {}
        if parts.username or parts.password:
            raise ValueError(
                f"rspace:// URLs must not contain credentials; put the API key in the "
                f"{KEY_ENV} environment variable instead")
        host = parts.netloc
        if not host:
            raise ValueError("rspace:// URL needs a host, e.g. rspace://my.rspace.host")
        params = {k: v[-1] for k, v in parse_qs(parts.query).items()}
        if "api_key" in params or "api_key_env" in params:
            raise ValueError(f"rspace:// URLs cannot carry or choose the API key; it is read from {KEY_ENV} only")
        scheme = params.get("scheme", "https")
        if scheme not in ("http", "https"):
            raise ValueError(f"scheme must be http or https, got {scheme!r}")
        if scheme == "http" and (parts.hostname or "") not in LOOPBACK_HOSTS:
            raise ValueError(
                f"scheme=http is only accepted for a local development server "
                f"({', '.join(LOOPBACK_HOSTS)}); {host!r} would receive the API key in clear text")
        kwargs: Dict[str, Any] = {"server": f"{scheme}://{host}"}
        if "writable" in params:
            kwargs["writable"] = _flag(params, "writable")
        if "allow_delete" in params:
            kwargs["allow_delete"] = _flag(params, "allow_delete")
        if "path_style" in params:
            kwargs["path_style"] = params["path_style"]
        if "mounts" in params:
            kwargs["mounts"] = tuple(m for m in params["mounts"].split(",") if m)
        return kwargs

    def _strip_host(self, path: str) -> str:
        """fsspec leaves the host in the path when a full URL is passed to a method
        (``fs.ls("rspace://host/gallery")``); drop it when it is this filesystem's host."""
        if self.server:
            host = urlsplit(self.server).netloc
            if path == host or path.startswith(host + "?"):
                return ""
            if path.startswith(host + "/"):
                # only a path that came in as a URL can carry a query string; a record's
                # own name may contain '?', so this is the one place it is cut off
                return path[len(host) + 1:].split("?", 1)[0].rstrip("/")
        return path

    # ------------------------------------------------------------ routing

    def _route(self, path: str) -> Tuple[str, RSpaceFSBase, str]:
        """``(mount name, branch, path inside the branch)`` for a path below the top level."""
        path = self._strip_host(self._strip_protocol(path))
        head, _, rest = path.partition("/")
        branch = self.branches.get(head)
        if branch is None:
            raise FileNotFoundError(errno.ENOENT, f"{path!r}: the top level holds {list(self.mount_names)}", path)
        return head, branch, rest

    def _is_top(self, path: str) -> bool:
        return "/" not in self._strip_host(self._strip_protocol(path))

    @staticmethod
    def _lift(head: str, entry: dict) -> dict:
        entry = dict(entry)
        entry["name"] = f"{head}/{entry['name']}".rstrip("/")
        return entry

    def _reject_root_write(self, path: str, op: str) -> None:
        if self._is_top(path):
            raise ReadOnlyError(
                errno.EROFS, f"{op}: the top level of an RSpaceFilesystem is fixed ({', '.join(self.mount_names)})",
                str(path))

    @property
    def read_only(self) -> bool:
        return not (self.writable or self.allow_delete)

    # ------------------------------------------------------------ listing and info

    def _mount_entry(self, name: str) -> dict:
        return make_entry(name, True, raw={"name": name, "mount": True})

    def scandir(self, path: str) -> Iterator[dict]:
        """Lazy listing, as in the branches."""
        path = self._strip_host(self._strip_protocol(path))
        if not path:
            return iter([self._mount_entry(name) for name in self.mount_names])
        head, branch, rest = self._route(path)
        return (self._lift(head, entry) for entry in branch.scandir(rest))

    def ls(self, path: str, detail: bool = True, refresh: bool = False, **kwargs) -> list:
        path = self._strip_host(self._strip_protocol(path))
        if not path:
            out = [self._mount_entry(name) for name in self.mount_names]
        else:
            head, branch, rest = self._route(path)
            out = [self._lift(head, entry) for entry in branch.ls(rest, detail=True, refresh=refresh, **kwargs)]
        return out if detail else [entry["name"] for entry in out]

    def info(self, path: str, **kwargs) -> dict:
        path = self._strip_host(self._strip_protocol(path))
        if not path:
            return make_entry("", True, raw={"name": "RSpace"})
        head, branch, rest = self._route(path)
        if not rest:
            return self._mount_entry(head)
        return self._lift(head, branch.info(rest, **kwargs))

    def glob(self, path: str, maxdepth: Optional[int] = None, **kwargs):
        path = self._strip_host(self._strip_protocol(path))
        head, _, rest = path.partition("/")
        if head in self.branches and rest:
            found = self.branches[head].glob(rest, maxdepth=maxdepth, **kwargs)
            if isinstance(found, dict):
                return {f"{head}/{name}": self._lift(head, entry) for name, entry in found.items()}
            return [f"{head}/{name}" for name in found]
        return super().glob(path, maxdepth=maxdepth, **kwargs)

    def created(self, path: str):
        _, branch, rest = self._route(path)
        return branch.created(rest)

    def modified(self, path: str):
        _, branch, rest = self._route(path)
        return branch.modified(rest)

    # ------------------------------------------------------------ files

    def _open(self, path: str, mode: str = "rb", block_size=None, autocommit: bool = True,
              cache_options=None, **kwargs):
        if self._is_top(path):
            if mode.startswith("r"):
                raise IsADirectoryError(errno.EISDIR, f"{path!r} is a directory", str(path))
            self._reject_root_write(path, "open")
        _, branch, rest = self._route(path)
        return branch._open(rest, mode=mode, block_size=block_size, autocommit=autocommit,
                            cache_options=cache_options, **kwargs)

    def cat_file(self, path: str, start: Optional[int] = None, end: Optional[int] = None, **kwargs) -> bytes:
        _, branch, rest = self._route(path)
        return branch.cat_file(rest, start=start, end=end, **kwargs)

    def download_fileobj(self, path: str, file, chunk_size: Optional[int] = None) -> None:
        """Stream the file at ``path`` into the open binary ``file``."""
        if self._is_top(path):
            raise IsADirectoryError(errno.EISDIR, f"{path!r} is a directory", str(path))
        _, branch, rest = self._route(path)
        branch.download_fileobj(rest, file, chunk_size=chunk_size)

    def upload_fileobj(self, path: str, file, **options: Any):
        """
        Upload into a Gallery folder, an Inventory record or a Workspace document field.

        Returns whatever the branch returns; a Gallery upload returns a
        :class:`~rspace_client.fs.gallery.Placement` describing where the file landed. Pass
        ``on_mismatch="reroute"`` to override the Gallery section policy for this call.
        """
        self._reject_root_write(path, "upload")
        _, branch, rest = self._route(path)
        return branch.upload_fileobj(rest, file, **options)

    def get_file(self, rpath: str, lpath, callback=None, outfile=None, **kwargs) -> None:
        if self._is_top(rpath):
            return
        _, branch, rest = self._route(rpath)
        branch.get_file(rest, lpath, callback=callback, outfile=outfile, **kwargs)

    def put_file(self, lpath, rpath: str, callback=None, mode: str = "overwrite", **kwargs) -> None:
        self._reject_root_write(rpath, "put")
        _, branch, rest = self._route(rpath)
        branch.put_file(lpath, rest, callback=callback, mode=mode, **kwargs)

    def link(self, path: str, media_file_gid: str) -> dict:
        """Link a Gallery file into the Inventory record, attachment field or document field
        at ``path`` without moving bytes."""
        self._reject_root_write(path, "link")
        _, branch, rest = self._route(path)
        if not hasattr(branch, "link"):
            raise NotImplementedError(f"{path!r}: the Gallery holds the files, it cannot link to them")
        return branch.link(rest, media_file_gid)

    # ------------------------------------------------------------ folders and removal

    def mkdir(self, path: str, create_parents: bool = True, **kwargs) -> None:
        self._reject_root_write(path, "mkdir")
        _, branch, rest = self._route(path)
        branch.mkdir(rest, create_parents=create_parents, **kwargs)

    def makedirs(self, path: str, exist_ok: bool = False) -> None:
        self._reject_root_write(path, "makedirs")
        _, branch, rest = self._route(path)
        branch.makedirs(rest, exist_ok=exist_ok)

    def rmdir(self, path: str) -> None:
        self._reject_root_write(path, "rmdir")
        _, branch, rest = self._route(path)
        branch.rmdir(rest)

    def rm_file(self, path: str) -> None:
        self._reject_root_write(path, "rm")
        _, branch, rest = self._route(path)
        branch.rm_file(rest)

    def rm(self, path, recursive: bool = False, maxdepth: Optional[int] = None) -> None:
        if recursive:
            raise NotImplementedError("recursive removal is not supported on RSpace")
        for one in ([path] if isinstance(path, str) else path):
            self._reject_root_write(one, "rm")
            _, branch, rest = self._route(one)
            branch.rm(rest)

    # ------------------------------------------------------------ copy and move

    def _gallery_file_behind(self, path: str) -> Optional[Tuple[str, Optional[str]]]:
        """``(global id, name)`` of the Gallery file a path resolves to, or None.

        Not only paths under ``gallery``: a file in an ELN document field *is* a Gallery
        file, and an Inventory attachment made through the Gallery names the file it points
        at. Any of those can be linked somewhere else without moving bytes.
        """
        if self._is_top(path):
            return None
        _, branch, rest = self._route(path)
        try:
            entry = branch.info(rest)
        except OSError:
            return None
        record = entry.get("rspace") or {}
        name = record.get("name")
        gid = str(record.get("globalId") or "")
        if gid.startswith("GL"):
            return gid, name
        # an Inventory attachment backed by the Gallery: link what it points at
        media = str(record.get("mediaFileGlobalId") or "")
        return (media, name) if media.startswith("GL") else None

    def cp_file(self, path1: str, path2: str, **kwargs) -> None:
        """
        Copy within RSpace. A Gallery file copied into Inventory or the Workspace is
        **linked**, not duplicated: no bytes move, and both places refer to the one file.

        This is what the web interface calls "link from Gallery". Without it a generic copy
        downloads the bytes and uploads them again, quietly leaving a second copy in the
        Gallery that the RSpace API cannot delete.

        A link keeps the Gallery file's own name, because that is all the API offers. Asking
        for a different name at the destination therefore falls through to a real copy, which
        does move the bytes, rather than silently creating something under the wrong name.
        """
        self._reject_root_write(path2, "copy")
        head, branch, rest = self._route(path2)
        branch._require_writable(rest)
        if head in ("inventory", "workspace"):
            source = self._gallery_file_behind(path1)
            if source is not None:
                gid, source_name = source
                container, wanted = branch._upload_target(rest)
                if wanted == source_name:
                    branch.link(container, gid)
                    return
        branch.upload_fileobj(rest, io.BytesIO(self.cat_file(path1)))

    def mv(self, path1: str, path2: str, recursive: bool = False, maxdepth: Optional[int] = None,
           **kwargs) -> None:
        """As in the branches: refuse before copying when the source cannot be removed."""
        self._reject_root_write(path2, "move")
        if self._is_top(path1):
            raise IsADirectoryError(errno.EISDIR, f"{path1!r} is a directory", str(path1))
        _, source, inner = self._route(path1)
        source._require_delete(inner)
        if not source.CAN_DELETE_FILES:
            raise NotImplementedError(
                f"{path1!r} cannot be moved: the RSpace API cannot delete a Gallery file, so only "
                f"a copy is possible")
        self.cp_file(path1, path2)
        self.rm_file(path1)

    # ------------------------------------------------------------ caches

    def clear_name_cache(self) -> None:
        """Forget resolved name lookups in every branch. Each branch clears its own after a
        change made through it; call this when records are renamed elsewhere."""
        for branch in self.branches.values():
            branch.clear_name_cache()

    def invalidate_cache(self, path: Optional[str] = None) -> None:
        super().invalidate_cache(path)
        self.dircache.clear()
        for branch in self.branches.values():
            branch.invalidate_cache()


# ``__init_subclass__`` above only sees subclasses of the mount; its own methods are
# translated here, so a 404 behind a path reaches callers as FileNotFoundError.
for _name in _TRANSLATED_METHODS:
    if _name in RSpaceFilesystem.__dict__:
        setattr(RSpaceFilesystem, _name, translate_api_errors(RSpaceFilesystem.__dict__[_name]))
del _name
