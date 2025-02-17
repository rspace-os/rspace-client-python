# This script implements a pyfilesystem for Inventory attachments.
# Inventory records -- containers, samples, subsamples, etc -- are modelled as
# directories, with each containing a set of attachments: the files.

import fs.base as FS
from rspace_client.inv import inv
from typing import Optional, List, Text, BinaryIO, Mapping, Any
from fs.info import Info
from fs.permissions import Permissions
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
        raise NotImplementedError()

    def listdir(self, path: Text) -> List[Text]:
        raise NotImplementedError()

    def makedir(self, path: Text, permissions: Optional[Permissions] = None, recreate: bool = False) -> SubFS[FS]:
        raise NotImplementedError()

    def openbin(self, path: Text, mode: Text = 'r', buffering: int = -1, **options) -> BinaryIO:
        raise NotImplementedError()

    def remove(self, path: Text) -> None:
        raise NotImplementedError()

    def removedir(self, path: Text) -> None:
        raise NotImplementedError()

    def setinfo(self, path: Text, info: Mapping[Text, Any]) -> None:
        raise NotImplementedError()

    def download(self, path: Text, file: BinaryIO, chunk_size: Optional[int] = None, **options: Any) -> None:
        raise NotImplementedError()

    def upload(self, path: Text, file: BinaryIO, chunk_size: Optional[int] = None, **options: Any) -> None:
        raise NotImplementedError()
