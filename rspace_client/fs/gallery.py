"""
fsspec view of the RSpace Gallery.

Gallery folders (``GF``) are directories and Gallery files (``GL``) are files. The
filesystem root is the Gallery's top folder, resolved lazily on first use, by
name, from the user's Home folder listing.

    fs = GalleryFilesystem(server, api_key)                 # read-only
    fs = GalleryFilesystem(server, api_key, writable=True)  # upload / mkdir allowed
    fs = GalleryFilesystem(eln_client=my_client)            # share a client (unified mount)
    fs = GalleryFilesystem(server, api_key, path_style="id") # bare 'GF12' segments instead of 'Images'

Listings are one request per directory. The folder-tree endpoint omits file sizes, and
consumers such as Galaxy need an integer size for every file, so by default each file in a
listing is topped up with its own record (``fetch_sizes=True``); pass ``fetch_sizes=False``
for a listing that stays at one request and reports ``size`` as None.

Gallery upload routing: the Gallery is split into media-type sections
(Images, Documents, Chemistry, ...) and a file may only be placed in a folder of the
matching section. ``upload_fileobj()`` returns a :class:`Placement`; when the target
folder's section rejects the file it either raises :class:`GallerySectionMismatch`
(``on_mismatch="raise"``, the default) or lets RSpace place the file in the correct
section and reports where it landed (``on_mismatch="reroute"``).
"""
from __future__ import annotations

import errno
import logging
from dataclasses import dataclass
from typing import Any, BinaryIO, Iterator, Mapping, Optional

from rspace_client.client_base import ClientBase
from rspace_client.eln import eln
from rspace_client.exceptions import RSpaceError

from . import paths
from .base import RSpaceFSBase, Target, client_or_new, deletes, make_entry, stream_pages, writes

logger = logging.getLogger(__name__)

FOLDER_PREFIXES = ("GF", "FL", "NB")
FILE_PREFIX = "GL"
#: The Gallery root is the folder of this name in the user's Home folder listing.
GALLERY_FOLDER_NAME = "Gallery"

# Accepted values for the ``on_mismatch`` policy.
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


def classify_media_section(filename: Optional[str]) -> Optional[str]:
    """
    Guess which Gallery section RSpace will file ``filename`` under, mirroring the
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


def _a_or_an(word: str) -> str:
    return "an" if word[:1].upper() in "AEIOU" else "a"


def check_policy(on_mismatch: str) -> str:
    if on_mismatch not in _ON_MISMATCH_VALUES:
        raise ValueError("on_mismatch must be one of {}".format(_ON_MISMATCH_VALUES))
    return on_mismatch


class GallerySectionMismatch(ClientBase.ApiError):
    """
    Raised when a file could not be uploaded into the requested Gallery folder
    because that folder belongs to a media-type section that does not accept the
    file. Carries the folder's section and, when it could be guessed, the file's
    media type, so callers can react programmatically as well as read the message.

    It is deliberately *not* translated into an ``OSError``: the message is written for the
    person in front of the screen and the attributes are what a library caller needs.
    """

    fs_passthrough = True

    def __init__(self, message, *, folder_section=None, folder_global_id=None,
                 file_media_type=None, response_status_code=None):
        super().__init__(message, response_status_code=response_status_code)
        self.folder_section = folder_section
        self.folder_global_id = folder_global_id
        self.file_media_type = file_media_type


@dataclass
class Placement:
    """Where an uploaded file actually ended up in the Gallery.

    Returned by :meth:`GalleryFilesystem.upload_fileobj`. When ``rerouted`` is True the
    file could not go into the requested folder and RSpace filed it in the section its
    media type belongs to; ``path`` is a readable description of where that is.
    """
    file_global_id: Optional[str]
    folder_global_id: Optional[str]
    section: Optional[str]
    path: str
    rerouted: bool
    requested_path: Optional[str] = None


def folder_section(eln_client: eln.ELNClient, folder_id) -> Optional[str]:
    """The Gallery section (mediaType) a folder belongs to, or None if it cannot be
    determined. Best-effort: never raises, so it cannot mask the real outcome of an upload."""
    try:
        return eln_client.get_folder(folder_id).get("mediaType")
    except RSpaceError:
        return None


def human_path(folder: Mapping[str, Any]) -> str:
    """Best-effort readable path for a folder, e.g. 'Gallery/Documents/Api Inbox'. Uses the
    API's pathToRootFolder when present, otherwise the section and folder name."""
    trail = folder.get("pathToRootFolder")
    names = [f.get("name") for f in trail if f.get("name")] if isinstance(trail, list) else []
    if names:
        return "/".join(names)
    return "/".join(["Gallery"] + [folder[k] for k in ("mediaType", "name") if folder.get(k)])


def placement(eln_client: eln.ELNClient, response: Any, requested_path: Optional[str],
              rerouted: bool) -> Placement:
    """Build a Placement from an upload response, resolving the parent folder for
    section/path feedback where possible. Tolerates a response that is not a dict (e.g.
    None): a caller may wrap ``upload_file`` and discard its return value, and Placement
    construction must never crash a successful upload."""
    if not isinstance(response, dict):
        response = {}
    folder: Mapping[str, Any] = {}
    parent_id = response.get("parentFolderId")
    if parent_id is not None:
        try:
            folder = eln_client.get_folder(parent_id)
        except RSpaceError:
            pass
    return Placement(
        file_global_id=response.get("globalId"),
        folder_global_id=folder.get("globalId"),
        section=folder.get("mediaType"),
        path=human_path(folder) if folder else "Gallery",
        rerouted=rerouted,
        requested_path=requested_path,
    )


def mismatch_message(named: str, container: str, section: str, guessed: Optional[str], err: Exception) -> str:
    """The explanation a person reads when a folder's section refuses their file."""
    message = (f"Could not upload {named} to Gallery folder {container or '/'}. That folder "
               f"is in the '{section}' section, which only accepts {section} files")
    if guessed and guessed != section:
        looks = ("does not match a specialised section and belongs in 'Miscellaneous'"
                 if guessed == MISCELLANEOUS_SECTION else f"looks like {_a_or_an(guessed)} '{guessed}' file")
        message += f", but {named} {looks}"
        remedy = f"Choose a folder in the '{guessed}' section instead"
    else:
        remedy = "Choose a folder in the section that matches this file type"
    # Lead with what the person in front of the screen can act on; the API-level option is
    # a parenthetical for library callers, who are not always the audience (this message
    # reaches Galaxy users verbatim).
    return message + (f". {remedy}, or upload without choosing a folder and RSpace will file it in the "
                      f"right section itself (library callers can pass on_mismatch='reroute' to do that "
                      f"automatically). Original API error: {err}")


class GalleryFilesystem(RSpaceFSBase):
    """Target kinds: root | folder | file."""

    protocol = ("rspace-gallery",)
    FILE_KINDS = ("file",)
    CAN_DELETE_FILES = False  # the RSpace API has no call to delete a Gallery file

    def __init__(self, server: Optional[str] = None, api_key: Optional[str] = None, *,
                 eln_client: Optional[eln.ELNClient] = None, writable: bool = False,
                 allow_delete: bool = False, path_style: str = "name",
                 on_mismatch: str = ON_MISMATCH_RAISE, page_size: int = 100,
                 fetch_sizes: bool = True, **storage_options: Any) -> None:
        super().__init__(writable=writable, allow_delete=allow_delete, path_style=path_style,
                         **storage_options)
        #: records fetched per API request while a listing is consumed, as in the other branches
        self.page_size = max(1, int(page_size))
        self.eln_client = client_or_new(eln_client, eln.ELNClient, server, api_key, "GalleryFilesystem")
        self.on_mismatch = check_policy(on_mismatch)
        #: fetch each file's own record while listing, because the folder-tree endpoint
        #: carries no size (one extra request per file)
        self.fetch_sizes = fetch_sizes
        self._gallery_id: Optional[int] = None

    # ------------------------------------------------------------ RSpace plumbing

    @property
    def gallery_id(self) -> int:
        """Numeric id of the Gallery root folder, looked up once on first use."""
        if self._gallery_id is None:
            for record in self._all_records(None):
                if record.get("name") == GALLERY_FOLDER_NAME:
                    self._gallery_id = int(record["id"])
                    break
            else:
                raise FileNotFoundError(
                    errno.ENOENT, f"no folder named {GALLERY_FOLDER_NAME!r} in the Home folder listing", "")
        return self._gallery_id

    def _all_records(self, folder_id) -> Iterator[dict]:
        """Stream a folder's contents, following the tree listing's 'next' links only as
        far as the consumer reads."""
        first_page = self.eln_client.list_folder_tree(folder_id, page_size=self.page_size)
        return stream_pages(self.eln_client, first_page, "records")

    def _resolve(self, path: str) -> Target:
        if paths.is_root(path):
            return Target("root")
        gid = self._gid_at(path)
        if gid[:2] in FOLDER_PREFIXES:
            return Target("folder", gid=gid)
        if gid[:2] == FILE_PREFIX:
            return Target("file", gid=gid)
        raise FileNotFoundError(errno.ENOENT, f"{path!r} not found", path)

    def _folder_id(self, path: str):
        """Numeric folder id for a directory path (root -> Gallery root)."""
        target = self._resolve(path)
        if target.kind == "root":
            return self.gallery_id
        if target.kind != "folder":
            raise NotADirectoryError(errno.ENOTDIR, f"{path!r} is a file", path)
        return target.gid[2:]

    def _record_entry(self, record: dict) -> dict:
        return self._entry(record, record["globalId"][:2] in FOLDER_PREFIXES)

    # ------------------------------------------------------------ listing and info

    def _children(self, target: Target, names_only: bool = False) -> Iterator[dict]:
        folder_id = self.gallery_id if target.kind == "root" else target.gid[2:]
        return self._scan_records(folder_id, self.fetch_sizes and not names_only)

    def _scan_records(self, folder_id, want_sizes: bool) -> Iterator[dict]:
        # One listing call per directory, plus one record fetch per file when sizes are
        # wanted: folder-tree items carry no size and consumers such as Galaxy require an
        # integer size for every file.
        for record in self._all_records(folder_id):
            if want_sizes and record.get("globalId", "")[:2] == FILE_PREFIX and record.get("size") is None:
                try:
                    record = self.eln_client.get_file_info(record["id"])
                except ClientBase.ApiError:  # keep listing even if one file cannot be read
                    logger.debug("could not read file details for %s", record.get("globalId"))
            yield self._record_entry(record)

    def _info_of(self, path: str, target: Target) -> dict:
        if target.kind == "root":
            return make_entry("", True, raw={"name": GALLERY_FOLDER_NAME})
        if target.kind == "folder":
            return self._entry(self.eln_client.get_folder(target.gid[2:]), True, target.gid)
        return self._entry(self.eln_client.get_file_info(target.gid[2:]), False, target.gid)

    # ------------------------------------------------------------ folders

    @writes
    def mkdir(self, path: str, create_parents: bool = True, exist_ok: bool = False, **kwargs) -> None:
        path = self._strip_protocol(path)
        if paths.is_root(path):
            raise FileExistsError(errno.EEXIST, "the root exists", path)
        parent, name = self._new_folder(path)
        folder_id = self._folder_id(parent)
        self._create_folder(path, name, self._all_records(folder_id),
                            lambda: self.eln_client.create_folder(name, folder_id),
                            FOLDER_PREFIXES, exist_ok)

    @deletes
    def rmdir(self, path: str) -> None:
        path = self._strip_protocol(path)
        target = self._resolve(path)
        self._remove_folder(path, target.gid if target.kind == "folder" else None,
                            self.eln_client.delete_folder,
                            NotADirectoryError(errno.ENOTDIR, f"{path!r} is not a folder", path))

    def rm_file(self, path: str) -> None:
        raise NotImplementedError("deleting Gallery files is not supported by the RSpace API")

    # ------------------------------------------------------------ files

    def _download(self, file_id: str, file: BinaryIO, chunk_size: int) -> None:
        self.eln_client.download_file(file_id, file, chunk_size)

    # ------------------------------------------------------------ upload with section routing

    @writes
    def upload_fileobj(self, path: str, file: BinaryIO, on_mismatch: Optional[str] = None,
                       **options: Any) -> Placement:
        """
        Write ``file`` to the Gallery file at ``path``: the last segment is the name to give
        the file and its parent is the folder to put it in. A file directly under the root
        is left to the API's default target, the relevant section's "Api Inbox".

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
        policy = check_policy(self.on_mismatch if on_mismatch is None else on_mismatch)
        path = self._strip_protocol(path)
        container, name = self._upload_target(path)
        folder_id = None if paths.is_root(container) else self._folder_id(container)
        try:
            response = self.eln_client.upload_file(file, folder_id, **self._upload_kwargs(name))
            self.invalidate_cache()
            return placement(self.eln_client, response, requested_path=container, rerouted=False)
        except ClientBase.ApiError as err:
            section = None if folder_id is None else folder_section(self.eln_client, folder_id)
            if section is None:
                raise
            filename = options.get("filename") or name
            guessed = classify_media_section(filename)

            if policy == ON_MISMATCH_REROUTE:
                try:
                    file.seek(0)
                except (AttributeError, OSError, ValueError):
                    pass
                response = self.eln_client.upload_file(file, None, **self._upload_kwargs(name))
                self.invalidate_cache()
                placed = placement(self.eln_client, response, requested_path=container, rerouted=True)
                logger.info(
                    "RSpace Gallery: %s could not go in %s (section '%s'); placed in %s instead",
                    f"'{filename}'" if filename else "file", container, section, placed.path)
                return placed

            # `from None` rather than `from err`: this exception reaches people through
            # Galaxy, which prints the whole chain and clips it from the top, hiding the
            # explanation at the bottom. The server's own reason is already quoted in the
            # message, and the original error stays available on the exception's
            # attributes, so nothing is lost by not stacking three tracebacks.
            raise GallerySectionMismatch(
                mismatch_message(f"'{filename}'" if filename else "the file", container, section, guessed, err),
                folder_section=section,
                folder_global_id="GF" + str(folder_id),
                file_media_type=guessed,
                response_status_code=getattr(err, "response_status_code", None),
            ) from None
