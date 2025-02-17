# This script implements a pyfilesystem for Inventory attachments.
# Inventory records -- containers, samples, subsamples, etc -- are modelled as
# directories, with each containing a set of attachments: the files.

from fs.base import FS
from rspace_client.inv import inv
from typing import Optional, List, Text, BinaryIO, Mapping, Any
from fs.info import Info
from fs.permissions import Permissions
from fs.subfs import SubFS
from fs import errors
from ..fs_utils import path_to_id

class InventoryAttachmentInfo(Info):
    def __init__(self, obj, *args, **kwargs) -> None:
        super().__init__(obj, *args, **kwargs)
        self.globalId = obj['rspace']['globalId'];

class InventoryAttachmentFilesystem(FS):

    def __init__(self, server: str, api_key: str) -> None:
        super(InventoryAttachmentFilesystem, self).__init__()
        self.inv_client = inv.InventoryClient(server, api_key)

    def getinfo(self, path, namespaces=None) -> Info:
        is_attachment = path.split('/')[-1][:2] == "IF"
        if not is_attachment:
            raise errors.ResourceNotFound(path)
        info = self.inv_client.get_attachment_by_id(path_to_id(path))
        return InventoryAttachmentInfo({
            "basic": {
                "name": path,
                "is_dir": False,
            },
            "details": {
                "size": info.get('size', 0),
                "type": "2",
            },
            "rspace": info,
        })

    def listdir(self, path: Text) -> List[Text]:
        raise NotImplementedError()

    def makedir(self, path: Text, permissions: Optional[Permissions] = None, recreate: bool = False) -> SubFS[FS]:
        raise NotImplementedError()

    def openbin(self, path: Text, mode: Text = 'r', buffering: int = -1, **options) -> BinaryIO:
        raise NotImplementedError()

    def remove(self, path: Text) -> None:
        is_attachment = path.split('/')[-1][:2] == "IF"
        if not is_attachment:
            raise errors.ResourceNotFound(path)
        self.inv_client.delete_attachment_by_id(path_to_id(path))

    def removedir(self, path: Text) -> None:
        raise NotImplementedError()

    def setinfo(self, path: Text, info: Mapping[Text, Any]) -> None:
        raise NotImplementedError()

    def download(self, path: Text, file: BinaryIO, chunk_size: Optional[int] = None, **options: Any) -> None:
        if chunk_size is not None:
            self.inv_client.download_attachment_by_id(path_to_id(path), file, chunk_size)
        else:
            self.inv_client.download_attachment_by_id(path_to_id(path), file)

    def upload(self, path: Text, file: BinaryIO, chunk_size: Optional[int] = None, **options: Any) -> None:
        raise NotImplementedError()
