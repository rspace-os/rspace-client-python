"""
Compatibility module so that the documented ``from rspace_client.inv import fs``
works (GitHub issue #57). Prefer ``rspace_client.fs.InventoryFilesystem``.
"""
from .attachment_fs import InventoryAttachmentFilesystem, InventoryAttachmentInfo  # noqa: F401

__all__ = ["InventoryAttachmentFilesystem", "InventoryAttachmentInfo"]
