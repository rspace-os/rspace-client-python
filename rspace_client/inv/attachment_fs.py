"""
Deprecated import location. Use ``rspace_client.fs.InventoryFilesystem`` instead.

This shim keeps existing code working: it exposes the same names and, unlike the
new class, is writable and allows deletion by default (the historical behaviour).
"""
import warnings

from ..fs.base import RSpaceInfo as InventoryAttachmentInfo  # noqa: F401  (historical name)
from ..fs.inventory import InventoryFilesystem as _InventoryFilesystem

_DEPRECATION = ("rspace_client.inv.attachment_fs.InventoryAttachmentFilesystem is deprecated; import "
                "rspace_client.fs.InventoryFilesystem instead (note: the new class is read-only "
                "unless writable=True / allow_delete=True are passed, browses the whole "
                "Inventory tree rather than a record's attachments alone, and takes the path "
                "of the file to create in upload() rather than the record to attach it to)")


class InventoryAttachmentFilesystem(_InventoryFilesystem):
    def __init__(self, server=None, api_key=None, *, writable=True, allow_delete=True, **kwargs):
        warnings.warn(_DEPRECATION, DeprecationWarning, stacklevel=2)
        kwargs.setdefault("path_style", "id")  # historical bare-ID paths
        # historical: the bytes became an Inventory-only file, never a Gallery item
        kwargs.setdefault("via_gallery", False)
        super().__init__(server, api_key, writable=writable, allow_delete=allow_delete, **kwargs)

    @staticmethod
    def _upload_kwargs(name):
        """These classes always took the uploaded file's name from the file object, so never
        send one explicitly: the request body stays byte-for-byte what it used to be."""
        return {}

    def _children(self, target):
        """Historic view: a record folder lists its attachments only, never the records
        inside it or its attachment fields, and is fetched without its contents."""
        if target.kind in ("root", "section", "field"):
            return super()._children(target)
        record = self._fetch(target.gid, include_content=False)
        return (self._file_info(a) for a in record.get("attachments", []))

    def upload(self, path, file, chunk_size=None, **options):
        """Historic convention: ``path`` is the *record* to attach to, and the file is named
        after the file object. The current class follows PyFilesystem instead."""
        name = getattr(file, "name", None) or "file"
        target = (path or "/").rstrip("/") + "/" + str(name).split("/")[-1]
        return super().upload(target, file, chunk_size, **options)


__all__ = ["InventoryAttachmentFilesystem", "InventoryAttachmentInfo"]
