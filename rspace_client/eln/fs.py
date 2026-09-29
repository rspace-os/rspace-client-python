"""
Deprecated import location. Use ``rspace_client.fs.GalleryFilesystem`` instead.

This shim keeps existing code working: it exposes the same names (including the
Gallery upload-routing API) and, unlike the new class, is writable,
allows deletion and uses bare global-ID paths by default (the historical behaviour).
"""
import warnings

from ..fs.base import RSpaceInfo as GalleryInfo  # noqa: F401  (historical name)
from ..fs.gallery import (  # noqa: F401  (historical re-exports)
    MISCELLANEOUS_SECTION,
    ON_MISMATCH_RAISE,
    ON_MISMATCH_REROUTE,
    GallerySectionMismatch,
    Placement,
    classify_media_section,
)
from ..fs.gallery import GalleryFilesystem as _GalleryFilesystem
from ..fs_utils import path_to_id  # noqa: F401  (historical re-export)

_DEPRECATION = ("rspace_client.eln.fs.GalleryFilesystem is deprecated; import "
                "rspace_client.fs.GalleryFilesystem instead (note: the new class is read-only "
                "unless writable=True / allow_delete=True are passed, names entries after the "
                "records themselves rather than by global ID, and takes the path of the file "
                "to create in upload() rather than the folder to put it in)")


def is_folder(path):
    return path.split("/")[-1][:2] == "GF"


class GalleryFilesystem(_GalleryFilesystem):
    def __init__(self, server=None, api_key=None, on_mismatch=ON_MISMATCH_RAISE, *,
                 writable=True, allow_delete=True, **kwargs):
        warnings.warn(_DEPRECATION, DeprecationWarning, stacklevel=2)
        kwargs.setdefault("path_style", "id")  # historical bare-ID paths
        super().__init__(server, api_key, on_mismatch=on_mismatch, writable=writable,
                         allow_delete=allow_delete, **kwargs)

    @staticmethod
    def _upload_kwargs(name):
        """These classes always took the uploaded file's name from the file object, so never
        send one explicitly: the request body stays byte-for-byte what it used to be."""
        return {}

    def upload(self, path, file, chunk_size=None, on_mismatch=None, **options):
        """Historic convention: ``path`` is the Gallery *folder* to upload into, and the file
        is named after the file object. The current class follows PyFilesystem instead."""
        name = getattr(file, "name", None) or "file"
        target = (path or "/").rstrip("/") + "/" + str(name).split("/")[-1]
        return super().upload(target, file, chunk_size, on_mismatch=on_mismatch, **options)

    def removedir(self, path, recursive=False, force=False):
        """The pre-2.8 signature accepted recursive/force; neither was ever honoured."""
        return super().removedir(path)


__all__ = [
    "GalleryFilesystem", "GalleryInfo", "GallerySectionMismatch", "Placement",
    "classify_media_section", "ON_MISMATCH_RAISE", "ON_MISMATCH_REROUTE",
    "MISCELLANEOUS_SECTION", "path_to_id", "is_folder",
]
