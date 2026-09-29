"""
PyFilesystem view of RSpace Inventory: every record is a folder that may hold files.

    /                         benches, plus the sections Containers, Samples, Templates
    /Containers               top-level containers, streamed however many there are
    /Samples, /Templates      likewise
    /WB user1a                a bench: its containers and subsamples, plus attachments
    /.../Freezer -80          a container: child containers and subsamples as folders,
                              attachments as files
    /.../Plasmid pUC19        a sample: its subsamples as folders, attachments as files
    /.../Plasmid pUC19 #1     a subsample: attachments, plus a shortcut folder
    /.../sample: Plasmid pUC19   the shortcut: that sample's attachments only (no subsamples,
                              so the tree has no cycles)
    /.../Plasmid              a sample template: attachments
    /.../microscope           an instrument: attachments
    /.../Safety Data          an attachment-type template field: the one file it holds

Segments are the records' own names under the default path style; a segment written as a
global ID (``IC200``, ``Freezer -80 [IC200]``) resolves whatever style is in force.

Records carry files in two places: their own ``attachments``, listed as files in the record
folder, and template-defined **attachment fields**, listed as folders holding at most one
file each (the same shape as an ELN document field). Only ``attachment`` fields are shown;
the other field types cannot hold a file. An attachment field accepts a file only while it
is empty: RSpace would replace the current file rather than add to it, which a folder does
not suggest, so uploading into an occupied field raises ``DestinationExists``. Remove the
file first (with ``allow_delete=True``) and then upload.

Samples are not stored *in* containers in RSpace, their subsamples are; the shortcut
folder is how you get from a subsample you found in a container to its sample's files.

A record listing is one API call. A section streams: its records are fetched
``page_size`` at a time as the listing is consumed, so a consumer that only wants the
first few entries (Galaxy passes its own limit/offset) does not pay for the rest.
Read-only by default: ``writable=True`` allows attaching files to any record,
``allow_delete=True`` allows removing attachments.
"""
from __future__ import annotations

from typing import BinaryIO, Collection, Iterator, List, Optional, Text

from fs import errors
from fs.info import Info

from rspace_client.client_base import Pagination
from rspace_client.eln import eln
from rspace_client.inv import inv

from . import paths
from .base import RSpaceFSBase, Target, client_or_new, deletes, make_info, stream_pages, writes

ATTACHMENT_PREFIX = "IF"
FIELD_PREFIX = "SF"  # a template-defined field on a sample, template or instrument
#: Inventory field types are number/date/string/text/uri/reference/attachment/time/radio/choice;
#: only "attachment" can hold a file, and it holds at most one.
FILE_BEARING_FIELD_TYPE = "attachment"
CONTAINER_PREFIXES = ("IC", "BE")
RECORD_GETTERS = {
    "IC": "get_container_by_id",
    "BE": "get_workbench_by_id",  # /containers/{id} answers 422 for a bench
    "SA": "get_sample_by_id",
    "SS": "get_subsample_by_id",
    "IT": "get_sample_template_by_id",
    "IN": "get_instrument_by_id",  # instruments can sit on a bench and carry attachments
}
#: Record types the server will actually attach a file to, confirmed live against RSpace
#: 2.27. A bench answers "Unsupported global id type" and a sample template answers "Sample
#: Templates don't support file attachments yet". Both present as ordinary record folders, so
#: without this the Gallery upload happens first and its file is stranded when the link is
#: refused, and the RSpace API cannot delete a Gallery file.
ATTACHABLE_PREFIXES = ("IC", "SA", "SS", "IN", "SF")
SECTION_LISTERS = {  # section -> (client method, collection key in the response)
    "Containers": ("list_top_level_containers", "containers"),
    "Samples": ("list_samples", "samples"),
    "Templates": ("list_sample_templates", "templates"),
}
#: The named sections at this filesystem's root, in the order they are listed.
SECTIONS = tuple(SECTION_LISTERS)


class InventoryFilesystem(RSpaceFSBase):
    """Target kinds: root | section | record | shortcut | field | attachment."""

    FILE_KINDS = ("attachment",)

    def __init__(self, server: Optional[str] = None, api_key: Optional[str] = None, *,
                 inv_client: Optional[inv.InventoryClient] = None,
                 eln_client: Optional[eln.ELNClient] = None, writable: bool = False,
                 allow_delete: bool = False, path_style: str = "name",
                 page_size: int = 100, via_gallery: Optional[bool] = None) -> None:
        super().__init__(writable=writable, allow_delete=allow_delete, path_style=path_style)
        self.inv_client = client_or_new(inv_client, inv.InventoryClient, server, api_key, "InventoryFilesystem")
        #: Put uploaded bytes in the Gallery and link them, rather than creating a file that
        #: exists only inside Inventory. See ``upload``. Needs an ELN client as well as an
        #: Inventory one; left as None it turns itself on whenever one can be had, and asking
        #: for it explicitly when one cannot is an error rather than a silent downgrade.
        if eln_client is None and via_gallery is not False and server and api_key:
            eln_client = eln.ELNClient(server, api_key)
        self.eln_client = eln_client
        if via_gallery and eln_client is None:
            raise ValueError(
                "via_gallery=True needs an ELN client as well as an Inventory one: pass "
                "eln_client=, or server and api_key, or via_gallery=False to create files "
                "that exist only inside Inventory")
        self.via_gallery = bool(eln_client) if via_gallery is None else via_gallery
        #: how many records to fetch per API request while streaming a listing; a
        #: performance knob, not something a user of the filesystem sees.
        self.page_size = max(1, int(page_size))

    # ------------------------------------------------------------ path grammar

    def _resolve(self, path: Text) -> Target:
        if paths.is_root(path):
            return Target("root")
        segments = paths.segments(path)
        section: Optional[str] = None
        previous_gid: Optional[str] = None
        target: Optional[Target] = None
        first = 0
        if segments[0] in SECTIONS:
            section = segments[0]
            first = 1
            if first == len(segments):
                return Target("section", section=section)
        for index, gid in self._gids(segments, first):
            prefix = gid[:2]
            if prefix == ATTACHMENT_PREFIX:
                if index != len(segments) - 1:  # nothing lives below a file
                    raise errors.ResourceNotFound(path)
                return Target("attachment", gid=gid, parent_gid=previous_gid)
            if prefix == FIELD_PREFIX:
                if previous_gid is None:
                    raise errors.ResourceNotFound(path)
                target = Target("field", gid=gid, parent_gid=previous_gid)
                previous_gid = gid
                continue
            if prefix not in RECORD_GETTERS:
                raise errors.ResourceNotFound(path)
            shortcut = prefix == "SA" and previous_gid is not None and previous_gid.startswith("SS")
            previous_gid = gid
            target = Target("shortcut" if shortcut else "record", gid=gid, section=section)
        if target is None:
            raise errors.ResourceNotFound(path)
        return target

    # ------------------------------------------------------------ RSpace plumbing

    def _fetch(self, gid: str, include_content: bool = True) -> dict:
        """Fetch a record. A container's contents cost extra to assemble server-side, so
        ``include_content=False`` when only the record itself is wanted (``getinfo``)."""
        getter = getattr(self.inv_client, RECORD_GETTERS[gid[:2]])
        if gid[:2] in CONTAINER_PREFIXES and include_content:
            return getter(gid[2:], include_content=True)
        return getter(gid[2:])

    def _section_items(self, section: str) -> Iterator[dict]:
        """Stream a section's records, fetching the next API page only when it is reached."""
        method, key = SECTION_LISTERS[section]
        first_page = getattr(self.inv_client, method)(Pagination(page_number=0, page_size=self.page_size))
        return stream_pages(self.inv_client, first_page, key)

    # ------------------------------------------------------------ Info builders

    def _file_info(self, attachment: dict, gid: Optional[str] = None) -> Info:
        return self._info(attachment, False, gid)

    @staticmethod
    def _virtual_dir(name: str, extra: Optional[dict] = None) -> Info:
        raw = {"name": name, "virtual": True}
        raw.update(extra or {})
        return make_info(name, True, raw=raw)

    @staticmethod
    def _file_bearing_fields(record: dict) -> List[dict]:
        """Template fields that can hold a file. Other field types are not browsable."""
        return [f for f in (record.get("fields") or [])
                if str(f.get("type", "")).lower() == FILE_BEARING_FIELD_TYPE and f.get("globalId")]

    def _field(self, record_gid: str, field_gid: str, record: Optional[dict] = None) -> dict:
        record = record if record is not None else self._fetch(record_gid)
        return self._find_field(self._file_bearing_fields(record), field_gid, record_gid)

    def _field_info(self, field: dict) -> Info:
        raw = dict(field, fieldType=field.get("type"))
        raw.pop("attachment", None)
        return self._info(raw, True)

    def _shortcut_info(self, sample: dict) -> Info:
        return self._info(dict(sample, shortcut="sample"), True, name=f"sample: {sample.get('name', '')}")

    # ------------------------------------------------------------ children of a directory

    def _children(self, target: Target) -> Iterator[Info]:
        if target.kind == "root":
            for bench in self.inv_client.get_workbenches():
                yield self._info(bench, True)
            for section in SECTIONS:
                yield self._virtual_dir(section, {"section": section})
            return

        if target.kind == "section":
            for item in self._section_items(target.section):
                yield self._info(item, True)
            return

        if target.kind == "field":
            attachment = self._field(target.parent_gid, target.gid).get("attachment")
            if attachment:
                yield self._file_info(attachment)
            return

        record = self._fetch(target.gid)
        prefix = target.gid[:2]
        if target.kind == "record":
            if prefix in CONTAINER_PREFIXES:
                for location in record.get("locations", []):
                    content = location.get("content")
                    if content and content.get("globalId"):
                        yield self._info(content, True)
            elif prefix == "SA":
                for sub in record.get("subSamples", []):
                    yield self._info(sub, True)
            elif prefix == "SS":
                sample = record.get("sample")
                if sample and sample.get("globalId"):
                    yield self._shortcut_info(sample)
            for field in self._file_bearing_fields(record):
                yield self._field_info(field)
        for attachment in record.get("attachments", []):
            yield self._file_info(attachment)

    # ------------------------------------------------------------ FS interface

    def getinfo(self, path: Text, namespaces: Optional[Collection[Text]] = None) -> Info:
        _path = self.validatepath(path)
        target = self._resolve(_path)
        if target.kind == "field":
            return self._field_info(self._field(target.parent_gid, target.gid))
        if target.kind == "root":
            return make_info("", True, raw={"name": "Inventory"})
        if target.kind == "section":
            return self._virtual_dir(target.section, {"section": target.section})
        if target.kind == "attachment":
            attachment = self.inv_client.get_attachment_by_id(target.gid[2:])
            return self._file_info(attachment, target.gid)
        record = self._fetch(target.gid, include_content=False)
        if target.kind == "shortcut":
            return self._shortcut_info(record)
        return self._info(record, True, target.gid)

    @deletes
    def remove(self, path: Text) -> None:
        _path = self.validatepath(path)
        target = self._resolve(_path)
        if target.kind != "attachment":
            raise errors.FileExpected(_path)
        self.inv_client.delete_attachment_by_id(target.gid[2:])
        self.clear_name_cache()

    def _file_source(self, _path: Text):
        target = self._resolve(_path)
        if target.kind != "attachment":
            raise errors.FileExpected(_path)
        return target.gid[2:], self.inv_client.download_attachment_by_id

    @writes
    def upload(self, path: Text, file: BinaryIO, chunk_size: Optional[int] = None, **options) -> None:
        """
        Write ``file`` to ``path``: the last segment names the attachment to create and its
        parent is the record (container, sample, subsample, instrument) or the attachment
        field to put it on.

        By default the bytes go to the **Gallery** and the record is given a link to them,
        which is what the web interface's "link from Gallery" does and what an ELN upload
        already did. The alternative, which the API also offers and which the deprecated
        ``InventoryAttachmentFilesystem`` keeps, creates a file that exists only inside
        Inventory: invisible in the Gallery, not reusable anywhere else, and impossible to
        find again except through the record it hangs off. Pass ``via_gallery=False`` for
        that behaviour.
        """
        _path, container, name, target = self._upload_prelude(path)
        if target.kind == "field":
            # An attachment field holds one file, and RSpace *replaces* it on a second upload
            # rather than adding. A folder looks like something you add to, so silently
            # destroying its contents would be a nasty surprise: refuse, and say what to do.
            # Checked before anything is uploaded, so a refusal leaves nothing behind.
            existing = self._field(target.parent_gid, target.gid).get("attachment")
            if existing:
                raise errors.DestinationExists(
                    container,
                    msg=f"{container!r} already holds {existing.get('name')!r}; an attachment field "
                        f"takes a single file and uploading would replace it. Remove the existing "
                        f"file first.")
        elif target.kind not in ("record", "shortcut"):
            raise errors.Unsupported(
                "upload", msg=f"{container!r}: files attach to a record or one of its attachment fields")
        if target.gid[:2] not in ATTACHABLE_PREFIXES:
            # Checked before the Gallery upload: the server would refuse the link afterwards
            # and the uploaded file could never be deleted.
            raise errors.Unsupported(
                "upload",
                msg=f"{container!r}: RSpace does not accept attachments on "
                    f"{'a bench' if target.gid[:2] == 'BE' else 'a sample template'}. "
                    f"Attach to a container, sample, subsample or instrument instead.")
        self._attach(target.gid, file, name)
        self.clear_name_cache()

    def _attach(self, parent_gid: Text, file: BinaryIO, name: Text) -> dict:
        """Put ``file`` on the record or field ``parent_gid``, through the Gallery unless
        ``via_gallery`` is off."""
        if not self.via_gallery:
            return self.inv_client.upload_attachment_by_global_id(
                parent_gid, file, **self._upload_kwargs(name))
        # No folder id: the Gallery files it into the section its media type belongs to, so
        # this cannot hit the section-mismatch rule that a chosen folder would.
        uploaded = self.eln_client.upload_file(file, **self._upload_kwargs(name))
        # by global id, not through link(): a field global id does not resolve as a path on
        # its own, because a field is only addressable underneath its record.
        return self.inv_client.attach_gallery_file_by_global_id(parent_gid, uploaded["globalId"])

    @writes
    def link(self, path: Text, media_file_gid: Text) -> dict:
        """Attach a file already in the Gallery to the record or attachment field at ``path``,
        without copying the bytes. The attachment reports the Gallery file it points at as
        ``mediaFileGlobalId``, and removing it leaves the Gallery file alone."""
        _path = self.validatepath(path)
        target = self._resolve(_path)
        if target.kind not in ("record", "shortcut", "field"):
            raise errors.Unsupported(
                "link", msg=f"{path!r}: a Gallery file links to a record or an attachment field")
        result = self.inv_client.attach_gallery_file_by_global_id(target.gid, media_file_gid)
        self.clear_name_cache()
        return result

