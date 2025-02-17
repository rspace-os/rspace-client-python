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
from fs.mode import Mode
from io import BytesIO
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
        global_id_prefix = path.split('/')[-1][:2]
        if global_id_prefix == "IC":
            dict = self.inv_client.get_container_by_id(path_to_id(path))
            if 'attachments' in dict:
                return [attachment['globalId'] for attachment in dict['attachments']]
        if global_id_prefix == "SA":
            dict = self.inv_client.get_sample_by_id(path_to_id(path))
            if 'attachments' in dict:
                return [attachment['globalId'] for attachment in dict['attachments']]
        if global_id_prefix == "SS":
            dict = self.inv_client.get_subsample_by_id(path_to_id(path))
            if 'attachments' in dict:
                return [attachment['globalId'] for attachment in dict['attachments']]
        if global_id_prefix == "IT":
            dict = self.inv_client.get_sample_template_by_id(path_to_id(path))
            if 'attachments' in dict:
                return [attachment['globalId'] for attachment in dict['attachments']]
        raise errors.ResourceNotFound(path)

    def makedir(self, path: Text, permissions: Optional[Permissions] = None, recreate: bool = False) -> SubFS[FS]:
        raise NotImplementedError()

    def openbin(self, path: Text, mode: Text = 'r', buffering: int = -1, **options) -> BinaryIO:
        """
        This method is added for conformance with the FS interface, but in
        almost all circumstances you probably want to be using upload and
        download directly as they have more information available e.g. uploaded
        files will have the same name as the source file when called directly
        """
        _mode = Mode(mode)
        if _mode.reading and _mode.writing:
            raise errors.Unsupported("read/write mode")
        if _mode.appending:
            raise errors.Unsupported("appending mode")
        if _mode.exclusive:
            raise errors.Unsupported("exclusive mode")
        if _mode.truncate:
            raise errors.Unsupported("truncate mode")

        if _mode.reading:
            file = BytesIO()
            self.download(path, file)
            file.seek(0)
            return file

        if _mode.writing:
            file = BytesIO()
            def upload_callback():
                file.seek(0)
                self.upload(path, file)
            file.close = upload_callback
            return file

        raise errors.Unsupported("mode {!r}".format(_mode))

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
        is_attachment = path.split('/')[-1][:2] == "IF"
        if not is_attachment:
            raise errors.ResourceNotFound(path)
        if chunk_size is not None:
            self.inv_client.download_attachment_by_id(path_to_id(path), file, chunk_size)
        else:
            self.inv_client.download_attachment_by_id(path_to_id(path), file)

    def upload(self, path: Text, file: BinaryIO, chunk_size: Optional[int] = None, **options: Any) -> None:
        global_id_prefix = path.split('/')[-1][:2]
        if global_id_prefix not in ["IC", "SS", "SA", "IT"]:
            raise errors.ResourceNotFound(path)
        self.inv_client.upload_attachment_by_global_id(path.split('/')[-1], file)
