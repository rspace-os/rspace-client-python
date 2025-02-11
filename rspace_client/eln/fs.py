from fs.base import FS
from rspace_client.eln import eln
from typing import Optional, List, Text, BinaryIO, Mapping
from fs.info import Info
from fs.permissions import Permissions
from fs.subfs import SubFS
from fs import errors
from typing import Any

def path_to_id(path):
    """
        A path is a slash-delimited string of Global Ids. The last element is
        the global id of the file or folder. This function extract just the id
        of the file or folder, which will be a string-encoding of a number.
    """
    global_id = path
    if '/' in path:
        global_id = path.split('/')[-1]
    return global_id[2:]


def is_folder(path):
    return path.split('/')[-1][:2] == "GF"


class GalleryInfo(Info):
    def __init__(self, obj, *args, **kwargs) -> None:
        super().__init__(obj, *args, **kwargs)
        self.globalId = obj['rspace']['globalId'];


class GalleryFilesystem(FS):

    def __init__(self) -> None:
        super(GalleryFilesystem, self).__init__()
        self.eln_client = eln.ELNClient("http://localhost:8080", "abcdefghijklmnop1")
        self.gallery_id = next(file['id'] for file in self.eln_client.list_folder_tree()['records'] if file['name'] == 'Gallery')

    def getinfo(self, path, namespaces=None) -> Info:
        is_file = path.split('/')[-1][:2] == "GL"
        info = None
        if is_folder(path):
            info = self.eln_client.get_folder(path_to_id(path))
        if is_file:
            info = self.eln_client.get_file_info(path_to_id(path))
        if info is None:
            raise errors.ResourceNotFound(path)
        return GalleryInfo({
            "basic": {
                "name": (is_folder(path) and "GF" or "GL") + path_to_id(path),
                "is_dir": is_folder(path),
            },
            "details": {
                "size": info.get('size', 0),
                "type": is_folder(path) and "1" or "2",
            },
            "rspace": info,
        })

    def listdir(self, path: Text) -> List[Text]:
        id = path in [u'.', u'/', u'./'] and self.gallery_id or path_to_id(path)
        return [file['globalId'] for file in self.eln_client.list_folder_tree(id)['records']]

    def makedir(self, path: Text, permissions: Optional[Permissions] = None, recreate: bool = False) -> SubFS[FS]:
        new_folder_name = path.split('/')[-1]
        parent_id = path_to_id(path[:-(len(new_folder_name) + 1)])
        new_id = self.eln_client.create_folder(new_folder_name, parent_id)['id']
        return self.opendir("/GF" + str(new_id))

    def openbin(self, path: Text, mode: Text = 'r', buffering: int = -1, **options) -> BinaryIO:
        raise NotImplementedError

    def remove(self, path: Text) -> None:
        raise NotImplementedError

    def removedir(self, path: Text, recursive: bool = False, force: bool = False) -> None:
        if path in [u'.', u'/', u'./']:
            raise errors.RemoveRootError()
        if (not is_folder(path)):
            raise errors.DirectoryExpected(path)
        if len(self.listdir(path)) > 0:
            raise errors.DirectoryNotEmpty(path)
        self.eln_client.delete_folder(path_to_id(path))

    def setinfo(self, path: Text, info: Mapping[Text, Mapping[Text, object]]) -> None:
        raise NotImplementedError

    def download(self, path: Text, file: BinaryIO, chunk_size: Optional[int] = None, **options: Any) -> None:
        if chunk_size is not None:
            self.eln_client.download_file(path_to_id(path), file, chunk_size)
        else:
            self.eln_client.download_file(path_to_id(path), file)
