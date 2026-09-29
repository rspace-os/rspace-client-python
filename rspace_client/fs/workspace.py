"""
PyFilesystem view of the RSpace ELN Workspace: folders, notebooks and documents as
folders, and the files linked into documents as files.

    /                                  the Home folder (system folders Gallery and Templates hidden)
    /Project Alpha/                    a folder: sub-folders, notebooks and documents
    /.../Lab notebook 2026/            a notebook: its entries (documents)
    /.../Alpha protocol/               a document: one folder per file-bearing field
    /.../Results/                      a text field: the files linked into it
    /.../data.csv                      a linked Gallery file

Segments are the records' own names under the default path style; a segment written as a
global ID (``SD42``, ``Alpha protocol [SD42]``) resolves whatever style is in force.

Only ``text`` fields are shown; the document's Info reports how many
fields were omitted under ``rspace.hiddenFields``. Text is the only ELN field type that
holds files: a file is linked to a document by a ``<fileId=N>`` token in a text field's
HTML, and in rspace-web every caller of ``Field.addMediaFileLink`` passes a text field.
The ``Attachment`` field type still exists in the model and the forms API accepts it, but
the form editor has only ever offered Number, String, Text, Radio, Choice, Date and Time
(``RSFormController.FIELD_KEYS``), so an attachment field is legacy and holds nothing.

Uploading into a text field uploads the file to the Gallery and appends a ``<fileId=N>``
link to that field; removing a file from a field unlinks it (the Gallery file is
untouched).
``makedir`` creates folders only (not notebooks or documents). A folder's contents are
streamed ``page_size`` records at a time, so listings of large folders stay lazy.
Read-only by default.
"""
from __future__ import annotations

import re
from typing import BinaryIO, Collection, Iterable, Iterator, List, Optional, Text

from bs4 import BeautifulSoup
from fs import errors
from fs.info import Info
from rspace_client.client_base import ClientBase
from rspace_client.eln import eln

from . import paths
from .base import RSpaceFSBase, Target, client_or_new, deletes, make_info, stream_pages, writes

FOLDER_PREFIXES = ("FL",)
NOTEBOOK_PREFIXES = ("NB",)
DOCUMENT_PREFIXES = ("SD",)
CONTAINER_PREFIXES = FOLDER_PREFIXES + NOTEBOOK_PREFIXES
FILE_PREFIX = "GL"
#: The only ELN field type that can hold files. See the module docstring: attachment
#: fields are legacy, are not offered by the form editor, and never carry linked media.
FILE_BEARING_FIELD_TYPES = ("text",)
#: System folders in the Home listing that this filesystem does not show: the Gallery root
#: is what /gallery is for, and Templates is not a place files live.
HIDDEN_ROOT_FOLDERS = ("Gallery", "Templates")
TREE_TYPES = ["folder", "notebook", "document"]


GALLERY_FILE_ID = re.compile(r"^(?:GL)?(\d+)$")


def _file_token(file_id) -> str:
    return f"<fileId={file_id}>"


def _gallery_file_number(media_file_gid) -> str:
    """The numeric part of a Gallery file id ('GL102' or '102' -> '102').

    The value ends up inside a document's HTML, so only a real file id is accepted: anything
    else is refused here rather than written into the field and left to the server."""
    match = GALLERY_FILE_ID.match(str(media_file_gid).strip())
    if not match:
        raise ValueError(f"{media_file_gid!r} is not a Gallery file id (expected 'GL<number>')")
    return match.group(1)


def strip_file_references(content: str, file_id) -> Optional[str]:
    """
    Remove everything in a field's HTML that references Gallery file ``file_id``:
    the literal ``<fileId=N>`` token the API accepts on write, and the markup the
    server renders it into on save (an ``attachmentDiv`` block whose link is
    ``attachOnText_N`` / ``/Streamfile/N``, or an ``img`` for images). Returns the
    new HTML, or None when nothing referenced the file.
    """
    file_id = str(file_id)
    token = _file_token(file_id)
    changed = token in content
    soup = BeautifulSoup(content.replace(token, ""), "html.parser")
    # exact forms the server uses, so a file id never matches a field id (e.g. sourceParentId=)
    reference = re.compile(rf"(?:Streamfile/|(?<![A-Za-z])sourceId=|attachOnText_|attachmentInfoDiv_){file_id}(?!\d)")
    image_id = re.compile(rf"^\d+-{file_id}$")  # <img id="<fieldId>-<fileId>" class="imageDropped">
    for tag in list(soup.find_all(True)):
        if tag.parent is None:  # already removed with an earlier block
            continue
        hit = False
        for name, value in tag.attrs.items():
            for v in (value if isinstance(value, list) else [value]):
                if isinstance(v, str) and (reference.search(v) or (name == "id" and image_id.match(v))):
                    hit = True
        if not hit:
            continue
        block = tag.find_parent("div", class_="attachmentDiv") or tag
        parent = block.parent
        if parent is not None:
            block.decompose()
            changed = True
            # an image sits in its own <p>; drop that paragraph if nothing else is left in it
            if parent.name == "p" and not parent.get_text(strip=True) and not parent.find(True):
                parent.decompose()
    return str(soup) if changed else None


class WorkspaceFilesystem(RSpaceFSBase):
    """Target kinds: root | folder | document | field | file. A field's ``parent_gid`` is its
    document; a file's ``parent_gid`` and ``field_gid`` are the document and field it was
    reached through."""

    FILE_KINDS = ("file",)

    def __init__(self, server: Optional[str] = None, api_key: Optional[str] = None, *,
                 eln_client: Optional[eln.ELNClient] = None, writable: bool = False,
                 allow_delete: bool = False, path_style: str = "name",
                 page_size: int = 100) -> None:
        super().__init__(writable=writable, allow_delete=allow_delete, path_style=path_style)
        self.eln_client = client_or_new(eln_client, eln.ELNClient, server, api_key, "WorkspaceFilesystem")
        #: how many records to fetch per API request while streaming a folder listing.
        self.page_size = max(1, int(page_size))

    # ------------------------------------------------------------ path grammar

    def _resolve(self, path: Text) -> Target:
        if paths.is_root(path):
            return Target("root")
        target = Target("root")
        for _, gid in self._gids(paths.segments(path)):
            prefix = gid[:2]
            if target.kind in ("root", "folder"):
                if prefix in CONTAINER_PREFIXES:
                    target = Target("folder", gid=gid)
                elif prefix in DOCUMENT_PREFIXES:
                    target = Target("document", gid=gid)
                else:
                    raise errors.ResourceNotFound(path)
            elif target.kind == "document":
                target = Target("field", gid=gid, parent_gid=target.gid, field_gid=gid)
            elif target.kind == "field":
                if prefix != FILE_PREFIX:
                    raise errors.ResourceNotFound(path)
                target = Target("file", gid=gid, parent_gid=target.parent_gid, field_gid=target.field_gid)
            else:
                raise errors.ResourceNotFound(path)
        return target

    # ------------------------------------------------------------ RSpace plumbing

    def _tree_items(self, folder_gid: Optional[str]) -> Iterator[dict]:
        """Stream a folder's contents, fetching the next API page only when it is reached."""
        first_page = self.eln_client.list_folder_tree(
            None if folder_gid is None else folder_gid[2:], TREE_TYPES, page_size=self.page_size)
        return stream_pages(self.eln_client, first_page, "records")

    def _document(self, doc_gid: str) -> dict:
        return self.eln_client.get_document(doc_gid[2:])

    @staticmethod
    def _visible_fields(document: dict) -> List[dict]:
        return [f for f in document.get("fields", []) if str(f.get("type", "")).lower() in FILE_BEARING_FIELD_TYPES]

    def _field(self, doc_gid: str, field_gid: str, document: Optional[dict] = None) -> dict:
        document = document or self._document(doc_gid)
        return self._find_field(self._visible_fields(document), field_gid, doc_gid)

    @staticmethod
    def _require_unsigned(document: dict, path: Text, extra: Text = "") -> None:
        """A signed document is locked; say so before touching the server."""
        if document.get("signed"):
            raise errors.ResourceReadOnly(
                path, msg=f"{path!r}: this document is signed, so its fields cannot be changed."
                          + (" " + extra if extra else ""))

    def _update_field_content(self, document: dict, field: dict, content: str) -> None:
        self._require_unsigned(document, document.get("globalId", ""))
        try:
            self.eln_client.update_document(
                document["id"], form_id=document.get("form", {}).get("id"),
                fields=[{"id": field["id"], "content": content}])
        except ClientBase.ApiError as exc:  # locked / signed documents
            if exc.response_status_code in (401, 403, 409, 423):
                raise errors.ResourceReadOnly(document.get("globalId", ""), msg=str(exc))
            raise

    # ------------------------------------------------------------ Info builders

    def _document_info(self, document: dict, gid: str) -> Info:
        raw = dict(document, hiddenFields=len(document.get("fields", [])) - len(self._visible_fields(document)))
        raw.pop("fields", None)
        return self._info(raw, True, gid, writable=not document.get("signed"))

    def _read_only_segment(self, name, gid: str, signed: bool) -> Text:
        """The field's path segment, marked when its document is locked.

        Only under the ``name`` style: the other two spell a segment so that a machine can
        parse it, and appending to ``Results [FD421]`` or to ``FD421`` would break that.
        """
        segment = self._segment(name, gid)
        return paths.mark_read_only(segment) if signed and self.path_style == "name" else segment

    def _field_info(self, field: dict, signed: bool = False) -> Info:
        """A field of a signed document is marked in its own name.

        This is the one place the lock can be surfaced for free: listing a document's fields
        already fetches the document, so ``signed`` is in hand. The document's own listing
        cannot say so, because the folder-tree endpoint the parent listing comes from does
        not carry the flag and finding out would cost a request per document.
        """
        raw = dict(field)
        raw.pop("files", None)
        raw.pop("content", None)
        raw["fieldType"] = field.get("type")
        raw["signed"] = signed
        return make_info(self._read_only_segment(field.get("name"), field["globalId"], signed),
                         True, raw=raw, modified=field.get("lastModified"),
                         writable=not signed)

    # ------------------------------------------------------------ children

    def _folder_children(self, folder_gid: Optional[str]) -> Iterator[Info]:
        yield from self._records_info(self._tree_items(folder_gid), folder_gid)

    def _hidden_at_root(self, record: dict) -> bool:
        """The Gallery root (a GF folder, duplicated by /gallery) and configured system folders."""
        if str(record.get("globalId", "")).startswith("GF"):
            return True
        return record.get("name") in HIDDEN_ROOT_FOLDERS and record.get("systemFolder", True) is not False

    def _records_info(self, records: Iterable[dict], folder_gid: Optional[str]) -> Iterator[Info]:
        for record in records:
            if folder_gid is None and self._hidden_at_root(record):
                continue
            yield self._info(record, True)

    def _children(self, target: Target) -> Iterator[Info]:
        if target.kind in ("root", "folder"):
            yield from self._folder_children(target.gid)
        elif target.kind == "document":
            document = self._document(target.gid)
            for field in self._visible_fields(document):
                yield self._field_info(field, signed=bool(document.get("signed")))
        else:  # field
            for file in self._field(target.parent_gid, target.field_gid).get("files", []):
                yield self._info(file, False)

    # ------------------------------------------------------------ FS interface

    def getinfo(self, path: Text, namespaces: Optional[Collection[Text]] = None) -> Info:
        _path = self.validatepath(path)
        target = self._resolve(_path)
        if target.kind == "root":
            return make_info("", True, raw={"name": "Workspace"})
        if target.kind == "folder":
            return self._info(self.eln_client.get_folder(target.gid[2:]), True, target.gid)
        if target.kind == "document":
            return self._document_info(self._document(target.gid), target.gid)
        if target.kind == "field":
            document = self._document(target.parent_gid)
            return self._field_info(self._field(target.parent_gid, target.field_gid, document),
                                    signed=bool(document.get("signed")))
        return self._info(self.eln_client.get_file_info(target.gid[2:]), False, target.gid)

    @writes
    def makedir(self, path: Text, permissions=None, recreate: bool = False):
        """Create a Workspace folder. Notebooks and documents are not created here."""
        _path = self.validatepath(path)
        parent_path, name = self._new_folder(_path)
        parent = self._resolve(parent_path)
        if parent.kind not in ("root", "folder") or (parent.gid or "FL")[:2] in NOTEBOOK_PREFIXES:
            raise errors.Unsupported("makedir", msg="folders can only be created in the Home folder or another folder")
        parent_id = parent.gid[2:] if parent.gid else None
        return self._create_folder(_path, parent_path, name, self._tree_items(parent.gid),
                                   lambda: self.eln_client.create_folder(name, parent_id, notebook=False),
                                   FOLDER_PREFIXES, recreate)

    def _folder_gid_at(self, _path: Text) -> Optional[Text]:
        target = self._resolve(_path)
        return target.gid if target.kind == "folder" and target.gid[:2] in FOLDER_PREFIXES else None

    @deletes
    def removedir(self, path: Text) -> None:
        _path = self.validatepath(path)
        self._remove_folder(_path, lambda: self._folder_gid_at(_path), self.eln_client.delete_folder,
                            errors.Unsupported("removedir", msg="only empty Workspace folders can be removed here"))

    def _file_source(self, _path: Text):
        target = self._resolve(_path)
        if target.kind != "file":
            raise errors.FileExpected(_path)
        return target.gid[2:], self.eln_client.download_file

    @writes
    def upload(self, path: Text, file: BinaryIO, chunk_size: Optional[int] = None, **options) -> None:
        """
        Write ``file`` to ``path``: the last segment names the file to create and its parent is
        the document field to link it into. The bytes go to the Gallery and the field gains a
        link to them.
        """
        _path, container, name, target = self._upload_prelude(path)
        if target.kind != "field":
            raise errors.Unsupported(
                "upload", msg=f"{container!r}: files are uploaded into a document field folder (a text field)")
        document = self._document(target.parent_gid)
        field = self._field(target.parent_gid, target.field_gid, document)
        # Checked before the upload: the field update afterwards would be refused and the
        # file would be stranded in the Gallery, which the API cannot delete.
        self._require_unsigned(document, container, "Nothing was uploaded.")
        uploaded = self.eln_client.upload_file(file, **self._upload_kwargs(name))
        self._update_field_content(document, field, (field.get("content") or "") + _file_token(uploaded["id"]))
        self.clear_name_cache()

    @writes
    def link(self, path: Text, media_file_gid: Text) -> dict:
        """Link a file already in the Gallery into the text field at ``path``, without
        copying the bytes. This is the same append an ``upload`` ends with, minus the upload."""
        _path = self.validatepath(path)
        target = self._resolve(_path)
        if target.kind != "field":
            raise errors.Unsupported(
                "link", msg=f"{path!r}: a Gallery file links into a document field (a text field)")
        document = self._document(target.parent_gid)
        field = self._field(target.parent_gid, target.field_gid, document)
        numeric = _gallery_file_number(media_file_gid)
        self._update_field_content(document, field, (field.get("content") or "") + _file_token(numeric))
        self.clear_name_cache()
        return self.eln_client.get_file_info(numeric)

    @deletes
    def remove(self, path: Text) -> None:
        """Unlink a file from its field. The Gallery file itself is left in place."""
        _path = self.validatepath(path)
        target = self._resolve(_path)
        if target.kind != "file":
            raise errors.FileExpected(_path)
        document = self._document(target.parent_gid)
        field = self._field(target.parent_gid, target.field_gid, document)
        stripped = strip_file_references(field.get("content") or "", target.gid[2:])
        if stripped is None:
            raise errors.ResourceNotFound(_path)
        self._update_field_content(document, field, stripped)
        self.clear_name_cache()
