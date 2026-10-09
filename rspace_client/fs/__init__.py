"""
fsspec (https://filesystem-spec.readthedocs.io) implementations for RSpace.

    from rspace_client.fs import GalleryFilesystem, InventoryFilesystem, WorkspaceFilesystem
    from rspace_client.fs import RSpaceFilesystem      # one mount: gallery/, inventory/, workspace/

    import fsspec                                      # key from RSPACE_API_KEY:
    fsspec.filesystem("rspace", server="https://my.rspace.host")
    fsspec.open("rspace://my.rspace.host/gallery/Images/microscope.png").open().read()

All filesystems are read-only by default. Pass ``writable=True`` to allow uploads and
folder creation, and ``allow_delete=True`` to allow removals. ``mounts=`` narrows what
``RSpaceFilesystem`` exposes, for a caller that only wants part of RSpace.

A path segment is the record's own name (``gallery/Images/microscope.png``). Where two
records in a folder share a name, the later ones carry their global ID before the extension
(``data [GL112].csv``). A segment written as a global ID always resolves, whatever style is
in force, and ``path_style="labelled"`` or ``"id"`` put one on every segment, which is what
you want if a stored path has to survive a rename. The full RSpace record for any entry is
under the ``rspace`` key of its info dict.
"""
import fsspec

from .base import RSpaceFSBase, ReadOnlyError, RemoteApiError, make_entry
from .gallery import GalleryFilesystem, GallerySectionMismatch, Placement
from .inventory import InventoryFilesystem
from .workspace import WorkspaceFilesystem
from .rspace import RSpaceFilesystem
from .tree import format_tree, print_tree

# also declared as an ``fsspec.specs`` entry point in pyproject.toml, so that
# ``fsspec.filesystem("rspace")`` works before this package was imported
fsspec.register_implementation("rspace", RSpaceFilesystem, clobber=True)

__all__ = [
    "RSpaceFSBase",
    "ReadOnlyError",
    "RemoteApiError",
    "make_entry",
    "GalleryFilesystem",
    "GallerySectionMismatch",
    "Placement",
    "InventoryFilesystem",
    "WorkspaceFilesystem",
    "RSpaceFilesystem",
    "format_tree",
    "print_tree",
]
