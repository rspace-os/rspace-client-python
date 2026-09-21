"""
PyFilesystem (https://docs.pyfilesystem.org) implementations for RSpace.

    from rspace_client.fs import GalleryFilesystem, InventoryFilesystem

    from rspace_client.fs import RSpaceFilesystem      # one mount: /gallery, /inventory, /workspace
    import fs; fs.open_fs("rspace://my.rspace.host")   # same, key from RSPACE_API_KEY

All filesystems are read-only by default. Pass ``writable=True`` to allow uploads and
folder creation, and ``allow_delete=True`` to allow removals. ``mounts=`` narrows what
``RSpaceFilesystem`` exposes, for a caller that only wants part of RSpace.

A path segment is the record's own name (``/gallery/Images/microscope.png``). Where two
records in a folder share a name, the later ones carry their global ID before the extension
(``data [GL112].csv``). A segment written as a global ID always resolves, whatever style is
in force, and ``path_style="labelled"`` or ``"id"`` put one on every segment, which is what
you want if a stored path has to survive a rename. The full RSpace record for any entry is
under the ``rspace`` namespace of its ``Info``.
"""
from .base import RSpaceFSBase, RSpaceInfo, make_info
from .gallery import GalleryFilesystem
from .inventory import InventoryFilesystem
from .workspace import WorkspaceFilesystem
from .rspace import RSpaceFilesystem
from .tree import format_tree, print_tree
from . import opener as _opener  # noqa: F401  (registers the rspace:// opener on import)

__all__ = [
    "RSpaceFSBase",
    "RSpaceInfo",
    "make_info",
    "GalleryFilesystem",
    "InventoryFilesystem",
    "WorkspaceFilesystem",
    "RSpaceFilesystem",
    "format_tree",
    "print_tree",
]
