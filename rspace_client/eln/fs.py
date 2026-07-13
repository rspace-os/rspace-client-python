from fs.base import FS
from rspace_client.eln import eln
from rspace_client.client_base import ClientBase
from typing import Optional, List, Text, BinaryIO, Mapping, Any
from fs.info import Info
from fs.permissions import Permissions
from fs.subfs import SubFS
from fs import errors
from fs.mode import Mode
from io import BytesIO
from ..fs_utils import path_to_id

# Best-effort mapping of file extension to the RSpace Gallery section that
# RSpace would classify it into. This mirrors the server's own classification
# but is NOT authoritative: it is used only to phrase error messages, never to
# decide whether an upload is allowed. Anything not listed falls through to the
# "Documents" catch-all, matching the server default.
_SECTION_BY_EXTENSION = {
    # Images
    "png": "Images", "jpg": "Images", "jpeg": "Images", "gif": "Images",
    "tif": "Images", "tiff": "Images", "bmp": "Images", "svg": "Images",
    "webp": "Images", "heic": "Images",
    # Audios
    "mp3": "Audios", "wav": "Audios", "flac": "Audios", "ogg": "Audios",
    "m4a": "Audios", "aac": "Audios", "wma": "Audios",
    # Videos
    "mp4": "Videos", "mov": "Videos", "avi": "Videos", "mkv": "Videos",
    "wmv": "Videos", "webm": "Videos", "m4v": "Videos", "flv": "Videos",
    # Chemistry
    "mol": "Chemistry", "mol2": "Chemistry", "rxn": "Chemistry",
    "cdx": "Chemistry", "cdxml": "Chemistry", "smi": "Chemistry",
    "sdf": "Chemistry", "cml": "Chemistry",
}


def classify_media_section(filename: Optional[Text]) -> Optional[Text]:
    """
    Best-effort guess of the Gallery section for a filename, mirroring RSpace's
    server-side classification. Returns a section name (e.g. "Images"), or
    "Documents" as the catch-all when the extension is unrecognised, or None
    when no filename/extension is available to guess from.

    The server remains the authority on placement; this is only used to make
    error messages and log lines more helpful.
    """
    if not filename or "." not in filename:
        return None
    ext = filename.rsplit(".", 1)[-1].lower()
    return _SECTION_BY_EXTENSION.get(ext, "Documents")


def _filename_for(file: BinaryIO, options: Mapping[Text, Any]) -> Optional[Text]:
    """Best-effort filename for a file object: an explicit ``filename`` option
    wins, otherwise the file object's own ``name`` if it is a string."""
    name = options.get("filename")
    if name:
        return name
    name = getattr(file, "name", None)
    return name if isinstance(name, str) else None


class GallerySectionMismatch(ClientBase.ApiError):
    """
    Raised when a file could not be uploaded into the requested Gallery folder
    because that folder belongs to a media-type section that does not accept the
    file. Carries the folder's section and, when it could be guessed, the file's
    media type, so callers can react programmatically as well as read the message.
    """

    def __init__(self, message, *, folder_section=None, folder_global_id=None,
                 file_media_type=None, response_status_code=None):
        super().__init__(message, response_status_code=response_status_code)
        self.folder_section = folder_section
        self.folder_global_id = folder_global_id
        self.file_media_type = file_media_type


def is_folder(path):
    return path.split('/')[-1][:2] == "GF"


class GalleryInfo(Info):
    def __init__(self, obj, *args, **kwargs) -> None:
        super().__init__(obj, *args, **kwargs)
        self.globalId = obj['rspace']['globalId'];


class GalleryFilesystem(FS):

    def __init__(self, server: str, api_key: str) -> None:
        super(GalleryFilesystem, self).__init__()
        self.eln_client = eln.ELNClient(server, api_key)
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

    def _folder_section(self, folder_id: Text) -> Optional[Text]:
        """The Gallery section (mediaType) a folder belongs to, or None if it
        cannot be determined. Used to explain upload failures."""
        try:
            return self.eln_client.get_folder(folder_id).get("mediaType")
        except ClientBase.ApiError:
            return None

    def upload(self, path: Text, file: BinaryIO, chunk_size: Optional[int] = None, **options: Any) -> None:
        """
        :param path: Global Id of a folder in the appropriate gallery section or
                     else if empty then the upload will be placed in the Api
                     Imports folder of the relevant gallery section
        :param file: a binary file object to be uploaded

        The RSpace Gallery is split into media-type sections (Images, Documents,
        Chemistry, ...) and a file may only be placed in a folder whose section
        matches the file's media type. If ``path`` names a folder in the wrong
        section the upload is rejected; this method re-raises that as a
        :class:`GallerySectionMismatch` naming the folder's section, instead of
        an opaque API error.
        """
        folder_id = path_to_id(path) if path else None
        try:
            self.eln_client.upload_file(file, folder_id)
        except ClientBase.ApiError as err:
            if folder_id is None:
                raise
            section = self._folder_section(folder_id)
            if section is None:
                raise
            filename = _filename_for(file, options)
            guessed = classify_media_section(filename)
            named = "'{}'".format(filename) if filename else "the file"
            message = (
                "Could not upload {named} to Gallery folder {path}. That folder "
                "is in the '{section}' section, which only accepts {section} "
                "files".format(named=named, path=path, section=section)
            )
            if guessed and guessed != section:
                message += ", but {named} looks like a '{guessed}' file".format(
                    named=named, guessed=guessed
                )
            message += (
                ". Upload it to a folder in the matching section, or omit the "
                "folder path to let RSpace place it in the correct section "
                "automatically. Original API error: {err}".format(err=err)
            )
            raise GallerySectionMismatch(
                message,
                folder_section=section,
                folder_global_id="GF" + str(folder_id),
                file_media_type=guessed,
                response_status_code=getattr(err, "response_status_code", None),
            ) from err
