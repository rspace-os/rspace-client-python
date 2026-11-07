"""
fsspec view of the RSpace ELN Workspace: folders, notebooks and documents as
folders, and the files linked into documents as files.

    (root)                             the Home folder (system folders Gallery and Templates hidden)
    Project Alpha/                     a folder: sub-folders, notebooks and documents
    .../Lab notebook 2026/             a notebook: its entries (documents)
    .../Alpha protocol/                a document: one folder per file-bearing field
    .../Results/                       a text field: the files linked into it
    .../data.csv                       a linked Gallery file

Segments are the records' own names under the default path style; a segment written as a
global ID (``SD42``, ``Alpha protocol [SD42]``) resolves whatever style is in force.

Only ``text`` fields are shown; the document's entry reports how many
fields were omitted under ``rspace.hiddenFields``. Text is the only ELN field type that
holds files: a file is linked to a document by a ``<fileId=N>`` token in a text field's
HTML, and in rspace-web every caller of ``Field.addMediaFileLink`` passes a text field.
The ``Attachment`` field type still exists in the model and the forms API accepts it, but
the form editor has only ever offered Number, String, Text, Radio, Choice, Date and Time
(``RSFormController.FIELD_KEYS``), so an attachment field is legacy and holds nothing.

Uploading into a text field uploads the file to the Gallery and appends a ``<fileId=N>``
link to that field; removing a file from a field unlinks it (the Gallery file is
untouched). A signed document is locked: every field write refuses before any request.

The API has no "append to a field": a link is added by sending the field's whole HTML back,
and the server keeps whichever write lands last. Field edits therefore hold a lock per
document within this process, and each one reads the field back and is applied again if a
writer elsewhere overwrote it. Two processes writing the same field at the same moment can
still lose a link; the server offers nothing to close that window.

A file segment written as a global ID is only accepted when the field really links that file,
so ``Results/GL112`` does not reach a Gallery file that lives somewhere else.

``mkdir`` creates folders only (not notebooks or documents). A folder's contents are
streamed ``page_size`` records at a time, so ``scandir`` of a large folder stays lazy.
Read-only by default.
"""

from __future__ import annotations

import errno
import re
import threading
from collections.abc import Callable, Iterable, Iterator
from typing import Any, BinaryIO

from bs4 import BeautifulSoup

from rspace_client.eln import eln

from . import paths
from .base import (
    ReadOnlyError,
    RSpaceFSBase,
    Target,
    client_or_new,
    deletes,
    make_entry,
    stream_pages,
    writes,
)

FOLDER_PREFIXES = ("FL",)
NOTEBOOK_PREFIXES = ("NB",)
DOCUMENT_PREFIXES = ("SD",)
CONTAINER_PREFIXES = FOLDER_PREFIXES + NOTEBOOK_PREFIXES
FILE_PREFIX = "GL"
#: System folders in the Home listing that this filesystem does not show: the Gallery root
#: is what the gallery branch is for, and Templates is not a place files live.
HIDDEN_ROOT_FOLDERS = ("Gallery", "Templates")
TREE_TYPES = ["folder", "notebook", "document"]


GALLERY_FILE_ID = re.compile(r"^(?:GL)?(\d+)$")
#: How often a field edit is sent before giving up because another writer keeps replacing the
#: field's content: the first write plus two re-applications.
FIELD_EDIT_ATTEMPTS = 3

#: One lock per (server, document), shared by every WorkspaceFilesystem in the process, so
#: that two threads editing fields of one document take turns instead of overwriting each other.
_document_locks: dict[tuple[str, str], threading.Lock] = {}
_document_locks_guard = threading.Lock()


def _document_lock(server: str, doc_gid: str) -> threading.Lock:
    with _document_locks_guard:
        return _document_locks.setdefault((server, doc_gid), threading.Lock())


def _file_token(file_id) -> str:
    return f"<fileId={file_id}>"


def _gallery_file_number(media_file_gid) -> str:
    """The numeric part of a Gallery file id ('GL102' or '102' -> '102').

    The value ends up inside a document's HTML, so only a real file id is accepted: anything
    else is refused here rather than written into the field and left to the server."""
    match = GALLERY_FILE_ID.match(str(media_file_gid).strip())
    if not match:
        raise ValueError(
            f"{media_file_gid!r} is not a Gallery file id (expected 'GL<number>')"
        )
    return match.group(1)


def strip_file_references(content: str, file_id) -> str | None:
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
    reference = re.compile(
        rf"(?:Streamfile/|(?<![A-Za-z])sourceId=|attachOnText_|attachmentInfoDiv_){file_id}(?!\d)"
    )
    image_id = re.compile(
        rf"^\d+-{file_id}$"
    )  # <img id="<fieldId>-<fileId>" class="imageDropped">
    for tag in list(soup.find_all(True)):
        if tag.parent is None:  # already removed with an earlier block
            continue
        hit = False
        for name, value in tag.attrs.items():
            for v in value if isinstance(value, list) else [value]:
                if isinstance(v, str) and (
                    reference.search(v) or (name == "id" and image_id.match(v))
                ):
                    hit = True
        if not hit:
            continue
        block = tag.find_parent("div", class_="attachmentDiv") or tag
        parent = block.parent
        if parent is not None:
            block.decompose()
            changed = True
            # an image sits in its own <p>; drop that paragraph if nothing else is left in it
            if (
                parent.name == "p"
                and not parent.get_text(strip=True)
                and not parent.find(True)
            ):
                parent.decompose()
    return str(soup) if changed else None


class WorkspaceFilesystem(RSpaceFSBase):
    """Target kinds: root | folder | document | field | file. A field's ``parent_gid`` is its
    document; a file's ``parent_gid`` and ``field_gid`` are the document and field it was
    reached through."""

    protocol = ("rspace-workspace",)
    FILE_KINDS = ("file",)
    #: The only ELN field type that can hold files. See the module docstring: attachment
    #: fields are legacy, are not offered by the form editor, and never carry linked media.
    FILE_BEARING_FIELD_TYPES = ("text",)
    CAN_LINK = True

    def __init__(
        self,
        server: str | None = None,
        api_key: str | None = None,
        *,
        eln_client: eln.ELNClient | None = None,
        writable: bool = False,
        allow_delete: bool = False,
        path_style: str = "name",
        page_size: int = 100,
        **storage_options: Any,
    ) -> None:
        super().__init__(
            writable=writable,
            allow_delete=allow_delete,
            path_style=path_style,
            **storage_options,
        )
        self.eln_client = client_or_new(
            eln_client, eln.ELNClient, server, api_key, "WorkspaceFilesystem"
        )
        #: how many records to fetch per API request while streaming a folder listing.
        self.page_size = max(1, int(page_size))

    # ------------------------------------------------------------ path grammar

    def _resolve(self, path: str) -> Target:
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
                    raise FileNotFoundError(errno.ENOENT, f"{path!r} not found", path)
            elif target.kind == "document":
                target = Target("field", gid=gid, parent_gid=target.gid, field_gid=gid)
            elif target.kind == "field":
                if prefix != FILE_PREFIX:
                    raise FileNotFoundError(errno.ENOENT, f"{path!r} not found", path)
                target = Target(
                    "file",
                    gid=gid,
                    parent_gid=target.parent_gid,
                    field_gid=target.field_gid,
                )
            else:
                raise FileNotFoundError(errno.ENOENT, f"{path!r} not found", path)
        return target

    # ------------------------------------------------------------ RSpace plumbing

    def _tree_items(self, folder_gid: str | None) -> Iterator[dict]:
        """Stream a folder's contents, fetching the next API page only when it is reached."""
        first_page = self.eln_client.list_folder_tree(
            None if folder_gid is None else folder_gid[2:],
            TREE_TYPES,
            page_size=self.page_size,
        )
        return stream_pages(self.eln_client, first_page, "records")

    def _record(self, doc_gid: str) -> dict:
        return self.eln_client.get_document(doc_gid[2:])

    @staticmethod
    def _require_unsigned(document: dict, path: str, extra: str = "") -> None:
        """A signed document is locked; say so before touching the server."""
        if document.get("signed"):
            raise ReadOnlyError(
                errno.EROFS,
                f"{path!r}: this document is signed, so its fields cannot be changed."
                + (" " + extra if extra else ""),
                path,
            )

    def _update_field_content(self, document: dict, field: dict, content: str) -> None:
        self._require_unsigned(document, document.get("globalId", ""))
        # a refusal by the server (401/403) reaches the caller as PermissionError through
        # the shared error translation; ReadOnlyError is for this filesystem's own posture
        self.eln_client.update_document(
            document["id"],
            form_id=document.get("form", {}).get("id"),
            fields=[{"id": field["id"], "content": content}],
        )

    @staticmethod
    def _links(field: dict, file_number: str) -> bool:
        """Whether the server's view of ``field`` links Gallery file ``file_number``."""
        return any(str(f.get("id")) == file_number for f in field.get("files") or [])

    def _edit_field(
        self,
        target: Target,
        edit: Callable[[str], str],
        applied: Callable[[dict], bool],
        what: str,
    ) -> None:
        """Change the HTML of the field ``target`` names and make sure the change stuck.

        ``edit`` turns the field's current content into the new content; ``applied`` says
        whether a field as the server returns it shows the change. The edit holds this
        process's lock on the document, then reads the field back: if a writer elsewhere
        replaced the content in between, the edit is applied again to what is there now.
        """
        server = getattr(self.eln_client, "rspace_url", "")
        with _document_lock(server, target.parent_gid):
            for attempt in range(FIELD_EDIT_ATTEMPTS):
                document = self._record(target.parent_gid)
                field = self._field(target.parent_gid, target.field_gid, document)
                if attempt and applied(
                    field
                ):  # the other writer's content already has it
                    return
                self._update_field_content(
                    document, field, edit(field.get("content") or "")
                )
                if applied(self._field(target.parent_gid, target.field_gid)):
                    return
        raise OSError(
            errno.EAGAIN,
            f"{target.field_gid} of {target.parent_gid}: {what} was overwritten by another "
            f"writer {FIELD_EDIT_ATTEMPTS} times; try again",
            target.field_gid,
        )

    # ------------------------------------------------------------ entry builders

    def _document_entry(self, document: dict, gid: str) -> dict:
        raw = dict(
            document,
            hiddenFields=len(document.get("fields", []))
            - len(self._file_fields(document)),
        )
        raw.pop("fields", None)
        return self._entry(raw, True, gid, writable=not document.get("signed"))

    def _read_only_segment(self, name, gid: str, signed: bool) -> str:
        """The field's path segment, marked when its document is locked.

        Only under the ``name`` style: the other two spell a segment so that a machine can
        parse it, and appending to ``Results [FD421]`` or to ``FD421`` would break that.
        """
        segment = self._segment(name, gid)
        return (
            paths.mark_read_only(segment)
            if signed and self.path_style == "name"
            else segment
        )

    def _field_entry(self, field: dict, signed: bool = False) -> dict:
        """A field of a signed document is marked in its own name.

        This is the one place the lock can be surfaced for free: listing a document's fields
        already fetches the document, so ``signed`` is in hand. The document's own entry in
        its parent listing cannot say so, because the folder-tree endpoint the parent listing
        comes from does not carry the flag and finding out would cost a request per document.
        """
        raw = dict(field)
        raw.pop("files", None)
        raw.pop("content", None)
        raw["fieldType"] = field.get("type")
        raw["signed"] = signed
        return make_entry(
            self._read_only_segment(field.get("name"), field["globalId"], signed),
            True,
            raw=raw,
            modified=field.get("lastModified"),
            writable=not signed,
        )

    # ------------------------------------------------------------ children

    def _hidden_at_root(self, record: dict) -> bool:
        """The Gallery root (a GF folder, duplicated by the gallery branch) and configured
        system folders."""
        if str(record.get("globalId", "")).startswith("GF"):
            return True
        return (
            record.get("name") in HIDDEN_ROOT_FOLDERS
            and record.get("systemFolder", True) is not False
        )

    def _records_entries(
        self, records: Iterable[dict], folder_gid: str | None
    ) -> Iterator[dict]:
        for record in records:
            if folder_gid is None and self._hidden_at_root(record):
                continue
            yield self._entry(record, True)

    def _children(self, target: Target, names_only: bool = False) -> Iterator[dict]:
        if target.kind in ("root", "folder"):
            return self._records_entries(self._tree_items(target.gid), target.gid)
        if target.kind == "document":
            document = self._record(target.gid)
            signed = bool(document.get("signed"))
            return (
                self._field_entry(field, signed=signed)
                for field in self._file_fields(document)
            )
        files = self._field(target.parent_gid, target.field_gid).get("files", [])
        return (self._entry(file, False) for file in files)

    # ------------------------------------------------------------ info

    def _info_of(self, path: str, target: Target) -> dict:
        if target.kind == "root":
            return make_entry("", True, raw={"name": "Workspace"})
        if target.kind == "folder":
            return self._entry(
                self.eln_client.get_folder(target.gid[2:]), True, target.gid
            )
        if target.kind == "document":
            return self._document_entry(self._record(target.gid), target.gid)
        if target.kind == "field":
            document = self._record(target.parent_gid)
            return self._field_entry(
                self._field(target.parent_gid, target.field_gid, document),
                signed=bool(document.get("signed")),
            )
        return self._entry(self._placed_file(path, target), False, target.gid)

    def _placed_file(self, path: str, target: Target) -> dict:
        """The file as the field it was reached through links it."""
        for file in self._field(target.parent_gid, target.field_gid).get("files") or []:
            if file.get("globalId") == target.gid:
                return file
        raise FileNotFoundError(
            errno.ENOENT, f"{path!r}: {target.gid} is not linked into this field", path
        )

    # ------------------------------------------------------------ folders

    @writes
    def mkdir(
        self, path: str, create_parents: bool = True, exist_ok: bool = False, **kwargs
    ) -> None:
        """Create a Workspace folder. Notebooks and documents are not created here."""
        path = self._strip_protocol(path)
        parent_path, name = self._new_folder(path)
        parent = self._resolve(parent_path)
        if (
            parent.kind not in ("root", "folder")
            or (parent.gid or "FL")[:2] in NOTEBOOK_PREFIXES
        ):
            raise NotImplementedError(
                "folders can only be created in the Home folder or another folder"
            )
        parent_id = parent.gid[2:] if parent.gid else None
        self._create_folder(
            path,
            name,
            self._tree_items(parent.gid),
            lambda: self.eln_client.create_folder(name, parent_id, notebook=False),
            FOLDER_PREFIXES,
            exist_ok,
        )

    @deletes
    def rmdir(self, path: str) -> None:
        path = self._strip_protocol(path)
        target = self._resolve(path)
        folder_gid = (
            target.gid
            if target.kind == "folder" and target.gid[:2] in FOLDER_PREFIXES
            else None
        )
        self._remove_folder(
            path,
            folder_gid,
            self.eln_client.delete_folder,
            NotImplementedError("only empty Workspace folders can be removed here"),
        )

    # ------------------------------------------------------------ files

    def _download(self, file_id: str, file: BinaryIO, chunk_size: int) -> None:
        self.eln_client.download_file(file_id, file, chunk_size)

    @writes
    def upload_fileobj(self, path: str, file: BinaryIO, **options: Any) -> dict:
        """
        Write ``file`` to ``path``: the last segment names the file to create and its parent is
        the document field to link it into. The bytes go to the Gallery and the field gains a
        link to them. Returns the Gallery file record.
        """
        path = self._strip_protocol(path)
        container, name = self._upload_target(path)
        target = self._resolve(container)
        if target.kind != "field":
            raise NotImplementedError(
                f"{container!r}: files are uploaded into a document field folder (a text field)"
            )
        document = self._record(target.parent_gid)
        self._field(target.parent_gid, target.field_gid, document)
        # Checked before the upload: the field update afterwards would be refused and the
        # file would be stranded in the Gallery, which the API cannot delete.
        self._require_unsigned(document, container, "Nothing was uploaded.")
        uploaded = self.eln_client.upload_file(file, **self._upload_kwargs(name))
        self._append_link(target, str(uploaded["id"]))
        self.invalidate_cache()
        return uploaded

    def _append_link(self, target: Target, file_number: str) -> None:
        self._edit_field(
            target,
            lambda content: content + _file_token(file_number),
            lambda field: self._links(field, file_number),
            f"the link to GL{file_number}",
        )

    @writes
    def link(self, path: str, media_file_gid: str) -> dict:
        """Link a file already in the Gallery into the text field at ``path``, without
        copying the bytes. This is the same append an upload ends with, minus the upload."""
        path = self._strip_protocol(path)
        target = self._resolve(path)
        if target.kind != "field":
            raise NotImplementedError(
                f"{path!r}: a Gallery file links into a document field (a text field)"
            )
        numeric = _gallery_file_number(media_file_gid)
        self._append_link(target, numeric)
        self.invalidate_cache()
        return self.eln_client.get_file_info(numeric)

    @deletes
    def rm_file(self, path: str) -> None:
        """Unlink a file from its field. The Gallery file itself is left in place."""
        path = self._strip_protocol(path)
        target = self._resolve(path)
        if target.kind != "file":
            raise IsADirectoryError(errno.EISDIR, f"{path!r} is not a file", path)
        file_number = target.gid[2:]

        def unlink(content: str) -> str:
            stripped = strip_file_references(content, file_number)
            if stripped is None:
                raise FileNotFoundError(
                    errno.ENOENT, f"{path!r} is not linked into this field", path
                )
            return stripped

        self._edit_field(
            target,
            unlink,
            lambda field: not self._links(field, file_number),
            f"the removal of {target.gid}",
        )
        self.invalidate_cache()
