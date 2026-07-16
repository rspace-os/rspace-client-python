import logging
from dataclasses import dataclass
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

logger = logging.getLogger(__name__)

# Accepted values for the GalleryFilesystem ``on_mismatch`` policy.
ON_MISMATCH_RAISE = "raise"
ON_MISMATCH_REROUTE = "reroute"
_ON_MISMATCH_VALUES = (ON_MISMATCH_RAISE, ON_MISMATCH_REROUTE)

# The RSpace Gallery's media-type sections. "Miscellaneous" is the catch-all
# that accepts any file not matching a more specific section; the others accept
# only their listed extensions (including "Documents", which is a fixed set, not
# a catch-all).
MISCELLANEOUS_SECTION = "Miscellaneous"

# Best-effort mapping of file extension to the Gallery section RSpace classifies
# it into, taken from the Gallery documentation. This mirrors the server's own
# classification but is NOT authoritative: it is used only to phrase error
# messages, never to decide whether an upload is allowed. Any extension not
# listed falls through to "Miscellaneous", matching the server default.
_SECTION_BY_EXTENSION = {
    # Images
    "png": "Images", "jpg": "Images", "jpeg": "Images", "gif": "Images",
    "bmp": "Images", "tif": "Images", "tiff": "Images",
    # Audios
    "mp3": "Audios", "wav": "Audios", "wma": "Audios", "aac": "Audios",
    "ogg": "Audios",
    # Videos
    "mp4": "Videos", "mov": "Videos", "hdmov": "Videos", "m4v": "Videos",
    "wmv": "Videos", "avi": "Videos", "mpg": "Videos", "mpeg": "Videos",
    "flv": "Videos", "3gp": "Videos",
    # Documents (a fixed set, NOT a catch-all)
    "doc": "Documents", "docx": "Documents", "rtf": "Documents",
    "pdf": "Documents", "odt": "Documents", "ods": "Documents",
    "odp": "Documents", "txt": "Documents", "ppt": "Documents",
    "pptx": "Documents", "xls": "Documents", "xlsx": "Documents",
    "csv": "Documents", "pps": "Documents", "md": "Documents",
    # Chemistry (documented subset; the server accepts more)
    "skc": "Chemistry", "mrv": "Chemistry", "cxsmiles": "Chemistry",
    "cxsmarts": "Chemistry", "cdx": "Chemistry", "cdxml": "Chemistry",
    "csrdf": "Chemistry", "cml": "Chemistry",
}


def classify_media_section(filename: Optional[Text]) -> Optional[Text]:
    """
    Best-effort guess of the Gallery section for a filename, mirroring RSpace's
    server-side classification. Returns a section name (e.g. "Images"),
    "Miscellaneous" as the catch-all when the extension is not one of a specific
    section's types, or None when no filename/extension is available to guess
    from.

    The server remains the authority on placement; this is only used to make
    error messages and log lines more helpful.
    """
    if not filename or "." not in filename:
        return None
    ext = filename.rsplit(".", 1)[-1].lower()
    return _SECTION_BY_EXTENSION.get(ext, MISCELLANEOUS_SECTION)


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


@dataclass
class Placement:
    """Where an uploaded file actually ended up in the Gallery.

    Returned by :meth:`GalleryFilesystem.upload`. When ``rerouted`` is True the
    file did not land in the folder named by ``requested_path`` (its section did
    not accept the file) and was placed in the correct section instead;
    ``path`` reports the human-readable location it ended up in.
    """
    file_global_id: Optional[Text]
    folder_global_id: Optional[Text]
    section: Optional[Text]
    path: Text
    rerouted: bool
    requested_path: Optional[Text] = None


def is_folder(path):
    return path.split('/')[-1][:2] == "GF"


class GalleryInfo(Info):
    def __init__(self, obj, *args, **kwargs) -> None:
        super().__init__(obj, *args, **kwargs)
        self.globalId = obj['rspace']['globalId'];


class GalleryFilesystem(FS):

    def __init__(self, server: str, api_key: str, on_mismatch: str = ON_MISMATCH_RAISE) -> None:
        """
        :param server: RSpace server URL
        :param api_key: RSpace API key
        :param on_mismatch: what to do when a file is uploaded to a folder whose
            Gallery section does not accept it. ``"raise"`` (default) raises a
            :class:`GallerySectionMismatch`; ``"reroute"`` instead places the
            file in the correct section automatically and reports where it
            landed. This is the filesystem-wide default and applies to every
            write (including generic PyFilesystem operations); individual
            :meth:`upload` calls may override it.
        """
        super(GalleryFilesystem, self).__init__()
        if on_mismatch not in _ON_MISMATCH_VALUES:
            raise ValueError(
                "on_mismatch must be one of {}".format(_ON_MISMATCH_VALUES)
            )
        self.on_mismatch = on_mismatch
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
        cannot be determined. Best-effort: never raises, so it cannot mask the
        real outcome of an upload."""
        try:
            return self.eln_client.get_folder(folder_id).get("mediaType")
        except Exception:
            return None

    def _human_path(self, folder: Mapping[Text, Any]) -> Text:
        """Best-effort readable path for a folder, e.g. 'Gallery/Documents/Api
        Inbox'. Uses the API's pathToRootFolder when present, otherwise falls
        back to the section and folder name."""
        trail = folder.get("pathToRootFolder")
        if isinstance(trail, list) and trail:
            names = [f.get("name") for f in trail if f.get("name")]
            if names:
                return "/".join(names)
        parts = ["Gallery"]
        if folder.get("mediaType"):
            parts.append(folder["mediaType"])
        if folder.get("name"):
            parts.append(folder["name"])
        return "/".join(parts)

    def _placement(self, response: Any, requested_path: Optional[Text],
                   rerouted: bool) -> Placement:
        """Build a Placement from an upload response, resolving the parent
        folder for section/path feedback where possible.

        Tolerates a response that is not a dict (e.g. None): some callers wrap
        or replace ``eln_client.upload_file`` and discard its return value, so
        Placement construction must never crash a successful upload.
        """
        if not isinstance(response, dict):
            response = {}
        parent_id = response.get("parentFolderId")
        section = None
        folder_global_id = None
        path = "Gallery"
        if parent_id is not None:
            try:
                folder = self.eln_client.get_folder(parent_id)
                section = folder.get("mediaType")
                folder_global_id = folder.get("globalId")
                path = self._human_path(folder)
            except Exception:
                pass
        return Placement(
            file_global_id=response.get("globalId"),
            folder_global_id=folder_global_id,
            section=section,
            path=path,
            rerouted=rerouted,
            requested_path=requested_path,
        )

    def upload(self, path: Text, file: BinaryIO, chunk_size: Optional[int] = None,
               on_mismatch: Optional[str] = None, **options: Any) -> Placement:
        """
        :param path: Global Id of a folder in the appropriate gallery section or
                     else if empty then the upload will be placed in the Api
                     Imports folder of the relevant gallery section
        :param file: a binary file object to be uploaded
        :param on_mismatch: optional override of the filesystem-wide policy for
                     this call ("raise" or "reroute"); defaults to the value
                     passed to the constructor.
        :return: a :class:`Placement` describing where the file ended up.

        The RSpace Gallery is split into media-type sections (Images, Documents,
        Chemistry, ...) and a file may only be placed in a folder whose section
        matches the file's media type. If ``path`` names a folder in the wrong
        section the upload is rejected. Depending on the effective policy this
        either raises a :class:`GallerySectionMismatch` naming the folder's
        section (``"raise"``) or places the file in the correct section's inbox
        and returns a Placement with ``rerouted=True`` (``"reroute"``).
        """
        policy = on_mismatch if on_mismatch is not None else self.on_mismatch
        if policy not in _ON_MISMATCH_VALUES:
            raise ValueError(
                "on_mismatch must be one of {}".format(_ON_MISMATCH_VALUES)
            )
        folder_id = path_to_id(path) if path else None
        try:
            response = self.eln_client.upload_file(file, folder_id)
            return self._placement(response, requested_path=path or None, rerouted=False)
        except ClientBase.ApiError as err:
            if folder_id is None:
                raise
            section = self._folder_section(folder_id)
            if section is None:
                raise
            filename = _filename_for(file, options)
            guessed = classify_media_section(filename)

            if policy == ON_MISMATCH_REROUTE:
                try:
                    file.seek(0)
                except (AttributeError, OSError, ValueError):
                    pass
                response = self.eln_client.upload_file(file, None)
                placement = self._placement(response, requested_path=path, rerouted=True)
                logger.info(
                    "RSpace Gallery: %s could not go in %s (section '%s'); "
                    "placed in %s instead",
                    "'{}'".format(filename) if filename else "file",
                    path, section, placement.path,
                )
                return placement

            named = "'{}'".format(filename) if filename else "the file"
            message = (
                "Could not upload {named} to Gallery folder {path}. That folder "
                "is in the '{section}' section, which only accepts {section} "
                "files".format(named=named, path=path, section=section)
            )
            if guessed and guessed != section:
                if guessed == MISCELLANEOUS_SECTION:
                    message += (
                        ", but {named} does not match a specialised section and "
                        "belongs in 'Miscellaneous'".format(named=named)
                    )
                else:
                    message += ", but {named} looks like a '{guessed}' file".format(
                        named=named, guessed=guessed
                    )
            message += (
                ". Upload it to a folder in the matching section, omit the "
                "folder path to let RSpace place it in the correct section "
                "automatically, or construct the filesystem with "
                "on_mismatch='reroute'. Original API error: {err}".format(err=err)
            )
            raise GallerySectionMismatch(
                message,
                folder_section=section,
                folder_global_id="GF" + str(folder_id),
                file_media_type=guessed,
                response_status_code=getattr(err, "response_status_code", None),
            ) from err
