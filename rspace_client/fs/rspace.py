"""
One filesystem across RSpace.

``RSpaceFilesystem`` is a PyFilesystem ``MountFS`` with the RSpace branches mounted
under fixed, human-readable top-level names, so that ``listdir("/")`` tells a user
what worlds exist:

    /gallery     the Gallery (GalleryFilesystem)
    /inventory   benches, Containers, Samples, Templates; every record is a folder (InventoryFilesystem)
    /workspace   ELN folders, notebooks, documents and their fields (WorkspaceFilesystem)

``mounts`` chooses which of those to expose, for a caller that only wants one part of RSpace
(a Galaxy file source, say, where the person configuring it picks what their group needs).
The names and the paths below them do not change, so narrowing the set later does not
invalidate paths to the branches that remain.

All branches share one ``ELNClient`` and one ``InventoryClient``, and one write
posture: read-only by default, ``writable=True`` for uploads and folder creation,
``allow_delete=True`` for removals. Paths are the records' own names by default
(``/gallery/Images/microscope.png``); pass ``path_style="labelled"`` for ``Name [GID]``
segments or ``path_style="id"`` for bare global IDs. A segment carrying a global ID is
accepted whatever the style. The top level itself is fixed and cannot be written to.

    fs = RSpaceFilesystem("https://rspace.example.org", api_key)
    fs.listdir("/")                         # ['gallery', 'inventory', 'workspace']
    fs.download("/gallery/Images/microscope.png", open("out.png", "wb"))

or, with ``RSPACE_API_KEY`` in the environment, ``fs.open_fs("rspace://rspace.example.org")``.
"""
from __future__ import annotations

from typing import Collection, Mapping, Optional, Text

from fs import errors
from fs.mountfs import MountFS
from fs.wrap import read_only

from rspace_client.eln import eln
from rspace_client.inv import inv

from . import paths
from .base import posture_meta
from .gallery import ON_MISMATCH_RAISE, GalleryFilesystem
from .inventory import InventoryFilesystem
from .workspace import WorkspaceFilesystem

MOUNTS = ("gallery", "inventory", "workspace")


class RSpaceFilesystem(MountFS):

    # set at class level too, so FS.__del__ works even if construction fails early
    auto_close = True

    def __init__(self, server: Optional[str] = None, api_key: Optional[str] = None, *,
                 eln_client: Optional[eln.ELNClient] = None,
                 inv_client: Optional[inv.InventoryClient] = None,
                 writable: bool = False, allow_delete: bool = False,
                 path_style: str = "name", on_mismatch: str = ON_MISMATCH_RAISE,
                 mounts: Collection[str] = MOUNTS) -> None:
        # before any validation, so a construction that fails still closes cleanly
        super().__init__(auto_close=True)
        # keep the canonical order however they were listed, so listdir('/') is stable
        chosen = tuple(name for name in MOUNTS if name in set(mounts))
        unknown = sorted(set(mounts) - set(MOUNTS))
        if unknown:
            raise ValueError(f"unknown mounts {unknown}, choose from {list(MOUNTS)}")
        if not chosen:
            raise ValueError(f"mounts cannot be empty, choose from {list(MOUNTS)}")
        # Only the clients the chosen branches use are required: every branch needs the ELN
        # client (Inventory uploads go through the Gallery), Inventory alone needs the other.
        can_build = bool(server and api_key)
        if eln_client is None and not can_build:
            raise ValueError("RSpaceFilesystem needs server and api_key, or an eln_client")
        if "inventory" in chosen and inv_client is None and not can_build:
            raise ValueError("RSpaceFilesystem needs server and api_key, or an inv_client, "
                             "to mount /inventory")
        #: which RSpace branches this filesystem exposes, in listing order. Not ``mounts``:
        #: MountFS already owns that attribute for its own (path, filesystem) pairs.
        self.mount_names = chosen
        self.server = server
        self.writable = writable
        self.allow_delete = allow_delete
        self.path_style = path_style

        self.eln_client = eln_client or eln.ELNClient(server, api_key)
        if inv_client is None and "inventory" in chosen:
            inv_client = inv.InventoryClient(server, api_key)
        #: None when /inventory is not mounted and no client was given
        self.inv_client = inv_client
        #: what to do when a file is uploaded to a Gallery folder whose media-type section
        #: does not accept it: "raise" (default) or "reroute" (let RSpace place it correctly).
        #: A single upload can override it with ``upload(..., on_mismatch=...)``.
        self.on_mismatch = on_mismatch
        posture = dict(writable=writable, allow_delete=allow_delete, path_style=path_style)
        builders = {
            "gallery": lambda: GalleryFilesystem(
                eln_client=self.eln_client, on_mismatch=on_mismatch, **posture),
            "inventory": lambda: InventoryFilesystem(
                inv_client=self.inv_client, eln_client=self.eln_client, **posture),
            "workspace": lambda: WorkspaceFilesystem(eln_client=self.eln_client, **posture),
        }
        #: each branch, or None when it was not mounted
        self.gallery = self.inventory = self.workspace = None
        for name in self.mount_names:
            branch = builders[name]()
            setattr(self, name, branch)
            self.mount(name, branch)
        # MountFS keeps the mount points in an in-memory filesystem and delegates writes to
        # it for any path outside a mount. Without this, writing to the top level would
        # quietly succeed and the bytes would be lost; there are too many write methods to
        # intercept individually, so make that filesystem read-only now that it is populated.
        self.default_fs = read_only(self.default_fs)

    def __repr__(self) -> str:
        return f"RSpaceFilesystem({self.server!r}, mounts={list(self.mount_names)}, writable={self.writable})"

    def __str__(self) -> str:
        return f"<rspace {self.server}>"

    def getmeta(self, namespace: Text = "standard") -> Mapping[Text, object]:
        meta = dict(super().getmeta(namespace))
        if namespace == "standard":
            posture_meta(meta, self.writable, self.allow_delete).update(network=True, supports_rename=False)
        return meta

    # The top level (the mount points) is fixed: refuse writes that would land in the
    # in-memory root instead of an RSpace branch.

    def _reject_root_write(self, path: Text, op: str) -> None:
        fs, _path = self._delegate(path)
        if fs is self.default_fs or paths.is_root(_path):
            raise errors.ResourceReadOnly(
                path, msg=f"{op}: the top level of an RSpaceFilesystem is fixed "
                          f"({', '.join(self.mount_names)})")

    def makedir(self, path: Text, permissions=None, recreate: bool = False):
        self._reject_root_write(path, "makedir")
        return super().makedir(path, permissions=permissions, recreate=recreate)

    def remove(self, path: Text) -> None:
        self._reject_root_write(path, "remove")
        super().remove(path)

    def removedir(self, path: Text) -> None:
        self._reject_root_write(path, "removedir")
        super().removedir(path)

    def upload(self, path: Text, file, chunk_size: Optional[int] = None, **options):
        """
        Upload into a Gallery folder, an Inventory record or a Workspace document field.

        Returns whatever the branch returns; a Gallery upload returns a
        :class:`~rspace_client.fs.gallery.Placement` describing where the file landed. Pass
        ``on_mismatch="reroute"`` to override the Gallery section policy for this call.
        """
        self._reject_root_write(path, "upload")
        fs, _path = self._delegate(path)
        return fs.upload(_path, file, chunk_size=chunk_size, **options)

    def clear_name_cache(self) -> None:
        """Forget resolved name lookups in every branch. Each branch clears its own after a
        change made through it; call this when records are renamed elsewhere."""
        for branch in (self.gallery, self.inventory, self.workspace):
            if branch is not None:
                branch.clear_name_cache()

    def _gallery_file_behind(self, path: Text):
        """``(global id, name)`` of the Gallery file a path resolves to, or None.

        Not only paths under ``/gallery``: a file in an ELN document field *is* a Gallery
        file, and an Inventory attachment made through the Gallery names the file it points
        at. Any of those can be linked somewhere else without moving bytes.
        """
        branch, inner = self._delegate(path)
        if branch is self.default_fs:
            return None
        try:
            info = branch.getinfo(inner)
        except errors.FSError:
            return None
        record = info.raw.get("rspace") or {}
        name = record.get("name")
        gid = str(record.get("globalId") or "")
        if gid.startswith("GL"):
            return gid, name
        # an Inventory attachment backed by the Gallery: link what it points at
        media = str(record.get("mediaFileGlobalId") or "")
        return (media, name) if media.startswith("GL") else None

    def copy(self, src_path: Text, dst_path: Text, overwrite: bool = False,
             preserve_time: bool = False, **options):
        """
        Copy within RSpace. A Gallery file copied into Inventory or the Workspace is
        **linked**, not duplicated: no bytes move, and both places refer to the one file.

        This is what the web interface calls "link from Gallery". Without it the generic
        PyFilesystem copy downloads the bytes and uploads them again, quietly leaving a
        second copy in the Gallery that the RSpace API cannot delete.

        A link keeps the Gallery file's own name, because that is all the API offers. Asking
        for a different name at the destination therefore falls through to a real copy, which
        does move the bytes, rather than silently creating something under the wrong name.
        """
        branch, inner = self._delegate(dst_path)
        linkable = branch is not None and branch in (self.inventory, self.workspace)
        source = self._gallery_file_behind(src_path) if linkable else None
        if source is not None:
            gid, source_name = source
            container, wanted = branch._upload_target(branch.validatepath(inner))
            if not overwrite and self.exists(dst_path):
                raise errors.DestinationExists(dst_path)
            # A link carries the Gallery file's own name, so only take the shortcut when that
            # is the name the caller asked for. Otherwise fall through and move the bytes.
            if wanted == source_name:
                return branch.link(container, gid)
        return super().copy(src_path, dst_path, overwrite=overwrite, preserve_time=preserve_time)

    def move(self, src_path: Text, dst_path: Text, overwrite: bool = False,
             preserve_time: bool = False) -> None:
        """As in the branches: refuse before copying when the source cannot be removed."""
        self._reject_root_write(dst_path, "move")
        source, inner = self._delegate(src_path)
        if source is self.default_fs:
            raise errors.FileExpected(src_path)
        source._require_delete(inner)
        super().move(src_path, dst_path, overwrite=overwrite, preserve_time=preserve_time)

    def download(self, path: Text, file, chunk_size: Optional[int] = None, **options) -> None:
        fs, _path = self._delegate(path)
        if fs is self.default_fs:
            raise errors.FileExpected(path)
        fs.download(_path, file, chunk_size=chunk_size, **options)
