"""
In-memory fixture dataset for the mock RSpace server, plus serialisers that
render records in the same JSON shapes the real RSpace ELN and Inventory APIs
return (field names taken from the server DTOs and from the recorded fixtures in
rspace_client/tests/data).

The dataset is deliberately small but realistic:

ELN (Workspace + Gallery)
  FL1  "user1a"            home folder
    GF2  "Gallery"          system folder (the Gallery root; GF id, as on real servers)
      GF10 "Images"           GL100 microscope.png, GL101 gel.jpg, GF13 "2026-09 run" (GL102 plate1.png)
      GF11 "Documents"        GL110 protocol.docx, GL111 data.csv, GL112 data.csv  (duplicate name on purpose)
      GF12 "Chemistry"        (empty)
      GF14 "Api Imports"      default upload target
    FL3  "Shared", FL4 "Templates", FL5 "Api Inbox", FL6 "Imports"   system folders
    FL20 "Project Alpha"
      NB30 "Lab notebook 2026"   SD40 "2026-09-15 entry", SD41 "2026-09-16 entry"
      SD42 "Alpha protocol"      custom form with TEXT/ATTACHMENT/NUMBER/DATE/STRING/CHOICE fields
                                 (only the two TEXT fields are browsable)
    FL21 "Project Beta"
      SD43 "Beta results"

Inventory
  BE1   "WB user1a"          workbench: IC203 "Bench box" (SS303), SS304
  IC200 "Freezer -80"        top level, attachment IF500; contains IC201 "Rack A" (grid: SS300, SS301), IC202 "Rack B" (SS302)
  IC204..IC215 "Shelf 1..12" top level, one subsample each (SS305..SS316)  -> makes /containers and /samples paginate
  SA1000 "Plasmid pUC19"     template IT1, attachment IF501, subsamples SS300 SS301 (SS300 has IF502)
  SA1001 "E. coli DH5a"      template IT2, subsamples SS302 SS303
  SA1002 "Buffer stock"      subsample SS304
  SA1003..SA1014 "Sample N"  one subsample each (15 samples in total)
  IT1 "Plasmid" (IF503), IT2 "Bacterial strain"
"""
from __future__ import annotations

import itertools
import mimetypes
import re
import threading
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

_T0 = datetime(2026, 9, 1, 9, 0, 0, tzinfo=timezone.utc)
FILE_ID_TOKEN = re.compile(r"<fileId=(\d+)>")
ATTACH_REF = re.compile(r'attachOnText_(\d+)"')


IMAGE_REF = re.compile(r"sourceType=IMAGE&amp;sourceId=(\d+)")


def render_attachment(file: dict, field_id: int = 0) -> str:
    """The HTML a real RSpace server stores in place of a <fileId=N> token (text fields)."""
    if str(file.get("contentType", "")).startswith("image/"):
        return (
            f'\n<p><img id="{field_id}-{file["id"]}" class="imageDropped inlineImageThumbnail" '
            f'src="/thumbnail/data?sourceType=IMAGE&amp;sourceId={file["id"]}&amp;sourceParentId={field_id}'
            f'&amp;width=1&amp;height=1&amp;rotation=0&amp;time=0" alt="image {file["name"]}" '
            f'width="1" height="1" data-size="1-1" data-rotation="0" /></p>'
        )
    return (
        '\n<div class="attachmentDiv mceNonEditable">\n'
        f' <a href="/Streamfile/{file["id"]}" target="_blank"> <img class="attachmentIcon" '
        f'src="/images/icons/{ext_of(file["name"]) or "file"}.png" height="32" width="32" /> </a>\n'
        f' <p class="attachmentP"><a class="attachmentLinked" id="attachOnText_{file["id"]}" '
        f'data-type="Documents" href="/Streamfile/{file["id"]}" target="_blank">{file["name"]}</a></p>\n'
        f' <div class="attachmentInfoDiv" id="attachmentInfoDiv_{file["id"]}">\n'
        '  <img class="attachmentInfoIcon" src="/images/getInfo12.png" />\n </div>\n</div>'
    )

OWNER = {
    "id": 1,
    "username": "user1a",
    "firstName": "User",
    "lastName": "One",
    "email": "user1a@example.com",
}

def iso(offset_minutes: int = 0) -> str:
    """ISO-8601 timestamp in the format RSpace uses, offset from a fixed epoch."""
    return (_T0 + timedelta(minutes=offset_minutes)).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def fake_blob(name: str, text: Optional[str] = None) -> bytes:
    """Deterministic file bytes; images get a real PNG/JPEG signature so mime sniffing works."""
    lower = name.lower()
    if text is not None:
        return text.encode("utf-8")
    if lower.endswith(".png"):
        return b"\x89PNG\r\n\x1a\n" + (b"mock-png-payload " * 64)
    if lower.endswith((".jpg", ".jpeg")):
        return b"\xff\xd8\xff\xe0" + (b"mock-jpeg-payload " * 48)
    if lower.endswith(".pdf"):
        return b"%PDF-1.4\n" + (b"% mock pdf\n" * 40) + b"%%EOF\n"
    return (f"mock content of {name}\n" * 20).encode("utf-8")


def guess_type(name: str, fallback: str = "application/octet-stream") -> str:
    return mimetypes.guess_type(name)[0] or fallback


def ext_of(name: str) -> str:
    return name.rsplit(".", 1)[-1].lower() if "." in name else ""


class MockData:
    """All mock state. Mutations are guarded by `lock` in the server."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.reset()

    # ------------------------------------------------------------------ build

    def reset(self) -> None:
        self._ids = itertools.count(10000)
        # ELN
        self.folders: Dict[int, dict] = {}  # FL / GF / NB
        self.gallery_files: Dict[int, dict] = {}  # GL
        self.documents: Dict[int, dict] = {}  # SD
        self.children: Dict[int, List[str]] = {}  # folder id -> [globalId, ...]
        self.forms = {1: "Basic Document", 2: "Experiment"}
        # Inventory
        self.containers: Dict[int, dict] = {}  # IC and BE (benches)
        self.samples: Dict[int, dict] = {}  # SA
        self.subsamples: Dict[int, dict] = {}  # SS
        self.templates: Dict[int, dict] = {}  # IT
        self.instruments: Dict[int, dict] = {}  # IN
        self.fields: Dict[int, dict] = {}  # SF (template-defined record fields)
        self.inv_files: Dict[int, dict] = {}  # IF
        # bytes for GL and IF, keyed by globalId
        self.blobs: Dict[str, bytes] = {}
        self._build()

    def new_id(self) -> int:
        return next(self._ids)

    # ELN builders -----------------------------------------------------------

    def _folder(self, fid: int, name: str, parent: Optional[int], prefix: str = "FL",
                notebook: bool = False, media_type: Optional[str] = None,
                system: bool = False, t: int = 0) -> dict:
        f = {
            "id": fid, "globalId": f"{prefix}{fid}", "name": name, "parentFolderId": parent,
            "notebook": notebook, "mediaType": media_type, "system": system,
            "created": iso(t), "lastModified": iso(t),
        }
        self.folders[fid] = f
        self.children.setdefault(fid, [])
        if parent is not None:
            self.children.setdefault(parent, []).append(f["globalId"])
        return f

    def _gfile(self, gid: int, name: str, parent: int, t: int = 0, text: Optional[str] = None,
               caption: str = "") -> dict:
        return self.add_gallery_file(name, parent, fake_blob(name, text), None, caption, gid=gid, t=t)

    def _doc(self, did: int, name: str, parent: int, form_id: int, fields: List[dict],
             t: int = 0, signed: bool = False) -> dict:
        for i, fld in enumerate(fields):
            fld.setdefault("columnIndex", i + 1)
            fld.setdefault("attachment_file_ids", [])
            fld["globalId"] = f"FD{fld['id']}"
            fld["lastModified"] = iso(t)
        d = {
            "id": did, "globalId": f"SD{did}", "name": name, "parentFolderId": parent,
            "formId": form_id, "tags": "", "created": iso(t), "lastModified": iso(t),
            "fields": fields, "signed": signed,
        }
        self.documents[did] = d
        self.children.setdefault(parent, []).append(d["globalId"])
        return d

    # Inventory builders -------------------------------------------------------

    def _container(self, cid: int, name: str, ctype: str = "LIST", parent: Optional[str] = None,
                   prefix: str = "IC", grid: Optional[tuple] = None, t: int = 0) -> dict:
        c = {
            "id": cid, "globalId": f"{prefix}{cid}", "name": name, "type": "CONTAINER",
            "cType": ctype, "description": "", "created": iso(t), "lastModified": iso(t),
            "parentGlobalId": parent, "gridLayout": (
                {"columnsNumber": grid[0], "rowsNumber": grid[1]} if grid else None),
            "attachment_ids": [], "content": [],  # content: list of child globalIds in location order
            "canStoreContainers": ctype != "GRID", "canStoreSamples": True,
        }
        self.containers[cid] = c
        if parent is not None:
            self.containers[int(parent[2:])]["content"].append(c["globalId"])
        return c

    def _sample(self, sid: int, name: str, template: Optional[int] = None, t: int = 0) -> dict:
        s = {
            "id": sid, "globalId": f"SA{sid}", "name": name, "type": "SAMPLE", "description": "",
            "created": iso(t), "lastModified": iso(t), "templateId": template,
            "quantity": {"numericValue": 10.0, "unitId": 3}, "subsample_ids": [],
            "attachment_ids": [], "tags": [], "fields": [],
        }
        self.samples[sid] = s
        return s

    def _subsample(self, ssid: int, name: str, sample: int, parent: Optional[str], t: int = 0) -> dict:
        ss = {
            "id": ssid, "globalId": f"SS{ssid}", "name": name, "type": "SUBSAMPLE",
            "created": iso(t), "lastModified": iso(t), "sampleId": sample,
            "parentGlobalId": parent, "quantity": {"numericValue": 1.0, "unitId": 3},
            "attachment_ids": [], "tags": [],
        }
        self.subsamples[ssid] = ss
        self.samples[sample]["subsample_ids"].append(ssid)
        if parent is not None:
            self.containers[int(parent[2:])]["content"].append(ss["globalId"])
        return ss

    def _template(self, tid: int, name: str, t: int = 0) -> dict:
        tpl = {
            "id": tid, "globalId": f"IT{tid}", "name": name, "type": "SAMPLE_TEMPLATE",
            "description": "", "created": iso(t), "lastModified": iso(t),
            "attachment_ids": [], "tags": [], "defaultUnitId": 3, "subSampleAlias": "subsample",
        }
        self.templates[tid] = tpl
        return tpl

    def _sample_field(self, record: dict, fid: int, name: str, ftype: str) -> dict:
        """A template-defined field (SF). Only an 'attachment' field holds a file, and one."""
        field = {"id": fid, "globalId": f"SF{fid}", "name": name, "type": ftype,
                 "content": None, "attachment_id": None}
        record.setdefault("fields", []).append(field)
        self.fields[fid] = field
        return field

    def _instrument(self, iid: int, name: str, parent: Optional[str] = None, t: int = 0) -> dict:
        ins = {
            "id": iid, "globalId": f"IN{iid}", "name": name, "type": "INSTRUMENT",
            "description": "", "created": iso(t), "lastModified": iso(t),
            "parentGlobalId": parent, "attachment_ids": [], "tags": [],
        }
        self.instruments[iid] = ins
        if parent is not None:
            self.containers[int(parent[2:])]["content"].append(ins["globalId"])
        return ins

    def _ifile(self, fid: int, name: str, parent_gid: str, t: int = 0, text: Optional[str] = None) -> dict:
        return self.add_inv_file(parent_gid, name, fake_blob(name, text), None, fid=fid, t=t)

    def _build(self) -> None:
        # ---- ELN tree
        self._folder(1, "user1a", None)
        self._folder(2, "Gallery", 1, prefix="GF", system=True)  # real servers use a GF id for the Gallery root
        self._folder(3, "Shared", 1, system=True)
        self._folder(4, "Templates", 1, system=True)
        self._folder(5, "Api Inbox", 1, system=True)
        self._folder(6, "Imports", 1, system=True)
        self._folder(10, "Images", 2, prefix="GF", media_type="Images", t=1)
        self._folder(11, "Documents", 2, prefix="GF", media_type="Documents", t=2)
        self._folder(12, "Chemistry", 2, prefix="GF", media_type="Chemistry", t=3)
        self._folder(13, "2026-09 run", 10, prefix="GF", media_type="Images", t=4)
        self._folder(14, "Api Imports", 2, prefix="GF", media_type="Documents", t=5)
        self._folder(20, "Project Alpha", 1, t=10)
        self._folder(21, "Project Beta", 1, t=11)
        self._folder(30, "Lab notebook 2026", 20, prefix="NB", notebook=True, t=12)

        self._gfile(100, "microscope.png", 10, t=20, caption="Confocal, 40x")
        self._gfile(101, "gel.jpg", 10, t=21)
        self._gfile(102, "plate1.png", 13, t=22)
        self._gfile(110, "protocol.docx", 11, t=23)
        self._gfile(111, "data.csv", 11, t=24, text="well,od600\nA1,0.41\nA2,0.39\n")
        self._gfile(112, "data.csv", 11, t=25, text="well,od600\nB1,0.52\nB2,0.48\n")

        self._doc(40, "2026-09-15 entry", 30, 1, [
            {"id": 400, "name": "Data", "type": "text",
             "content": "<p>Imaging session, see image.</p><fileId=100>"},
        ], t=30)
        self._doc(41, "2026-09-16 entry", 30, 1, [
            {"id": 410, "name": "Data", "type": "text", "content": "<p>No images yet.</p>"},
        ], t=31)
        self._doc(42, "Alpha protocol", 20, 2, [
            {"id": 420, "name": "Objective", "type": "text",
             "content": "<p>Express pUC19 in DH5a and check yield.</p>"},
            {"id": 421, "name": "Results", "type": "text",
             "content": "<p>See attached data and plate image.</p><fileId=111><fileId=102>"},
            # A legacy Attachment field: the form editor cannot create one and nothing links
            # media to it, so it is always empty and the filesystem does not list it.
            {"id": 422, "name": "Raw data", "type": "attachment", "content": ""},
            {"id": 423, "name": "Replicates", "type": "number", "content": "3"},
            {"id": 424, "name": "Run date", "type": "date", "content": "2026-09-15"},
            {"id": 425, "name": "Operator", "type": "string", "content": "user1a"},
            {"id": 426, "name": "Status", "type": "choice", "content": "in progress"},
        ], t=32)
        self._doc(44, "Signed protocol", 20, 1, [
            # holds one linked file, so that unlinking from a signed document can be tested
            {"id": 440, "name": "Data", "type": "text", "content": "<p>witnessed</p><fileId=102>"},
        ], t=34, signed=True)
        self._doc(43, "Beta results", 21, 1, [
            {"id": 430, "name": "Data", "type": "text", "content": "<p>Second run.</p><fileId=112>"},
        ], t=33)

        # ---- Inventory
        self._container(1, "WB user1a", ctype="WORKBENCH", prefix="BE")
        self._container(200, "Freezer -80", t=40)
        self._container(201, "Rack A", ctype="GRID", parent="IC200", grid=(2, 2), t=41)
        self._container(202, "Rack B", parent="IC200", t=42)
        self._container(203, "Bench box", parent="BE1", t=43)
        for i in range(12):
            self._container(204 + i, f"Shelf {i + 1}", t=44 + i)

        self._template(1, "Plasmid", t=50)
        self._template(2, "Bacterial strain", t=51)

        self._sample(1000, "Plasmid pUC19", template=1, t=60)
        self._sample(1001, "E. coli DH5a", template=2, t=61)
        self._sample(1002, "Buffer stock", t=62)
        self._subsample(300, "Plasmid pUC19 #1", 1000, "IC201", t=63)
        self._subsample(301, "Plasmid pUC19 #2", 1000, "IC201", t=64)
        self._subsample(302, "E. coli DH5a #1", 1001, "IC202", t=65)
        self._subsample(303, "E. coli DH5a #2", 1001, "IC203", t=66)
        self._subsample(304, "Buffer stock #1", 1002, "BE1", t=67)
        for i in range(12):  # one extra sample per shelf IC204..IC215
            sid = 1003 + i
            self._sample(sid, f"Sample {sid - 1000}", t=70 + i)
            self._subsample(305 + i, f"Sample {sid - 1000} #1", sid, f"IC{204 + i}", t=70 + i)

        self._sample_field(self.samples[1000], 700, "Safety Data", "attachment")
        self._sample_field(self.samples[1000], 701, "Concentration", "number")
        self._sample_field(self.samples[1001], 702, "Datasheet", "attachment")  # deliberately empty
        self._instrument(2, "Confocal microscope", parent="BE1", t=52)
        self._ifile(504, "calibration.pdf", "IN2", t=84)
        self._ifile(505, "msds.pdf", "SF700", t=85)  # a file held by an attachment field
        self._ifile(500, "freezer_manual.pdf", "IC200", t=80)
        self._ifile(501, "plasmid_map.gb", "SA1000", t=81, text="LOCUS pUC19 2686 bp DNA circular\n")
        self._ifile(502, "qc_gel.png", "SS300", t=82)
        self._ifile(503, "template_notes.txt", "IT1", t=83, text="Notes for the plasmid template.\n")

    # ------------------------------------------------------------------ lookups

    def record_by_global_id(self, gid: str) -> dict:
        prefix, num = gid[:2], int(gid[2:])
        table = {
            "FL": self.folders, "GF": self.folders, "NB": self.folders, "GL": self.gallery_files,
            "SD": self.documents, "IC": self.containers, "BE": self.containers,
            "SA": self.samples, "SS": self.subsamples, "IT": self.templates,
            "IN": self.instruments, "IF": self.inv_files, "SF": self.fields,
        }.get(prefix)
        if table is None or num not in table:
            raise KeyError(gid)
        return table[num]

    def gallery_root_id(self) -> int:
        return 2

    def home_id(self) -> int:
        return 1

    def is_gallery_folder(self, fid: int) -> bool:
        f = self.folders.get(fid)
        return bool(f) and (f["globalId"].startswith("GF") or fid == self.gallery_root_id())

    def top_level_containers(self) -> List[dict]:
        return [c for c in self.containers.values()
                if c["parentGlobalId"] is None and c["cType"] != "WORKBENCH"]

    def benches(self) -> List[dict]:
        return [c for c in self.containers.values() if c["cType"] == "WORKBENCH"]

    # ------------------------------------------------------------------ mutations

    def add_folder(self, name: str, parent: Optional[int], notebook: bool) -> dict:
        parent = parent if parent is not None else self.home_id()
        if parent not in self.folders:
            raise KeyError(f"FL{parent}")
        prefix = "GF" if self.is_gallery_folder(parent) else ("NB" if notebook else "FL")
        media = self.folders[parent].get("mediaType") if prefix == "GF" else None
        return self._folder(self.new_id(), name, parent, prefix=prefix, notebook=notebook and prefix == "NB",
                            media_type=media, t=100)

    def remove_folder(self, fid: int) -> None:
        f = self.folders[fid]
        if self.children.get(fid):
            raise ValueError("folder is not empty")
        parent = f["parentFolderId"]
        if parent is not None:
            self.children[parent].remove(f["globalId"])
        del self.folders[fid]
        del self.children[fid]

    def add_gallery_file(self, name: str, parent: Optional[int], content: bytes,
                         content_type: Optional[str], caption: str = "", gid: Optional[int] = None,
                         t: int = 200) -> dict:
        parent = parent if parent is not None else 14  # "Api Imports"
        if not self.is_gallery_folder(parent) or parent == self.gallery_root_id():
            raise ValueError(f"folder {parent} is not a Gallery folder that can hold files")
        gid = self.new_id() if gid is None else gid
        g = {
            "id": gid, "globalId": f"GL{gid}", "name": name, "caption": caption,
            "contentType": content_type or guess_type(name), "created": iso(t), "size": len(content),
            "version": 1, "parentFolderId": parent,
        }
        self.gallery_files[gid] = g
        self.blobs[g["globalId"]] = content
        self.children.setdefault(parent, []).append(g["globalId"])
        return g

    def update_document(self, did: int, payload: dict) -> dict:
        d = self.documents[did]
        if payload.get("name"):
            d["name"] = payload["name"]
        if "tags" in payload and payload["tags"] is not None:
            d["tags"] = payload["tags"]
        by_id = {f["id"]: f for f in d["fields"]}
        for upd in payload.get("fields") or []:
            fld = by_id.get(upd.get("id"))
            if fld is None:
                raise KeyError(f"field {upd.get('id')} not in document SD{did}")
            if "content" in upd:
                content = upd["content"]
                if fld["type"] == "text":  # like the server: tokens become attachment markup on save
                    content = FILE_ID_TOKEN.sub(
                        lambda m: render_attachment(self.gallery_files[int(m.group(1))], fld["id"])
                        if int(m.group(1)) in self.gallery_files else "", content)
                fld["content"] = content
                fld["lastModified"] = iso(201)
        d["lastModified"] = iso(201)
        return d

    def link_gallery_file(self, parent_gid: str, media_gid: str) -> dict:
        """The server's "link from Gallery": no bytes move, and the resulting Inventory file
        names the Gallery file it points at. Benches and sample templates are refused, as the
        real server refuses them."""
        if parent_gid[:2] in ("BE",):
            raise ValueError(f"Unsupported global id type: {parent_gid}")
        if parent_gid[:2] in ("IT",):
            raise ValueError("Sample Templates don't support file attachments yet")
        gallery = next((f for f in self.gallery_files.values()
                        if f.get("globalId") == media_gid), None)
        if gallery is None:
            raise ValueError(f"no such Gallery file: {media_gid}")
        linked = self.add_inv_file(parent_gid, gallery["name"],
                                   self.blobs.get(media_gid, b""), gallery.get("contentType"))
        linked["mediaFileGlobalId"] = media_gid
        return linked

    def add_inv_file(self, parent_gid: str, name: str, content: bytes, content_type: Optional[str],
                     fid: Optional[int] = None, t: int = 202) -> dict:
        if parent_gid[:2] not in ("IC", "SA", "SS", "IT", "IN", "SF"):
            raise ValueError(f"{parent_gid} cannot hold attachments")
        parent = self.record_by_global_id(parent_gid)
        fid = self.new_id() if fid is None else fid
        a = {
            "id": fid, "globalId": f"IF{fid}", "name": name, "parentGlobalId": parent_gid,
            "mediaFileGlobalId": None, "type": "GENERAL", "contentMimeType": content_type or guess_type(name),
            "extension": ext_of(name), "size": len(content), "created": iso(t),
            "createdBy": OWNER["username"], "deleted": False,
        }
        self.inv_files[fid] = a
        self.blobs[a["globalId"]] = content
        if parent_gid.startswith("SF"):  # a field holds one file; a new one replaces it
            previous = parent.get("attachment_id")
            if previous is not None:
                self.inv_files[previous]["deleted"] = True
            parent["attachment_id"] = fid
        else:
            parent["attachment_ids"].append(fid)
        return a

    def remove_inv_file(self, fid: int) -> None:
        a = self.inv_files.pop(fid)
        parent = self.record_by_global_id(a["parentGlobalId"])
        if a["parentGlobalId"].startswith("SF"):
            if parent.get("attachment_id") == fid:
                parent["attachment_id"] = None
        else:
            parent["attachment_ids"].remove(fid)
        self.blobs.pop(a["globalId"], None)


# ============================================================ API serialisers
# Each takes the record and the API base URL (e.g. http://host:port/api/v1) so
# that _links are absolute and share the client's origin.

def _self(base: str, path: str) -> List[dict]:
    return [{"link": f"{base}{path}", "rel": "self"}]


def ser_folder(f: dict, base: str) -> dict:
    return {
        "id": f["id"], "globalId": f["globalId"], "name": f["name"], "created": f["created"],
        "lastModified": f["lastModified"], "parentFolderId": f["parentFolderId"],
        "notebook": f["notebook"], "mediaType": f["mediaType"], "pathToRootFolder": None,
        "_links": _self(base, f"/folders/{f['id']}"),
    }


def ser_gallery_file(g: dict, base: str) -> dict:
    return {
        "id": g["id"], "globalId": g["globalId"], "name": g["name"], "caption": g["caption"],
        "contentType": g["contentType"], "created": g["created"], "size": g["size"],
        "version": g["version"], "parentFolderId": g["parentFolderId"],
        "_links": _self(base, f"/files/{g['id']}") + [
            {"link": f"{base}/files/{g['id']}/file", "rel": "enclosure"}],
    }


def ser_tree_item(gid: str, data: MockData, base: str) -> dict:
    rec = data.record_by_global_id(gid)
    prefix = gid[:2]
    if prefix in ("FL", "GF"):
        typ, link = "FOLDER", f"/folders/{rec['id']}"
    elif prefix == "NB":
        typ, link = "NOTEBOOK", f"/folders/{rec['id']}"
    elif prefix == "SD":
        typ, link = "DOCUMENT", f"/documents/{rec['id']}"
    else:
        typ, link = "MEDIA_FILE", f"/files/{rec['id']}"
    item = {
        "id": rec["id"], "globalId": gid, "name": rec["name"], "created": rec["created"],
        "lastModified": rec.get("lastModified", rec["created"]), "parentFolderId": rec.get("parentFolderId"),
        "type": typ, "owner": OWNER, "_links": _self(base, link),
    }
    if typ == "FOLDER":  # real servers flag system and shared folders on folder tree items
        item["systemFolder"] = bool(rec.get("system"))
        item["sharedFolder"] = rec.get("name") == "Shared"
    return item


def field_file_ids(fld: dict) -> List[int]:
    if fld["type"] == "text":
        content = fld.get("content") or ""
        ids = ([int(m) for m in FILE_ID_TOKEN.findall(content)] + [int(m) for m in ATTACH_REF.findall(content)]
               + [int(m) for m in IMAGE_REF.findall(content)])
        return list(dict.fromkeys(ids))  # unique, in order
    if fld["type"] == "attachment":
        return list(fld.get("attachment_file_ids") or [])
    return []


def ser_document(d: dict, data: MockData, base: str) -> dict:
    fields = []
    for fld in d["fields"]:
        files = [ser_gallery_file(data.gallery_files[i], base)
                 for i in field_file_ids(fld) if i in data.gallery_files]
        fields.append({
            "id": fld["id"], "globalId": fld["globalId"], "name": fld["name"], "type": fld["type"],
            "content": fld.get("content", ""), "lastModified": fld["lastModified"],
            "columnIndex": fld["columnIndex"], "files": files, "listOfMaterials": [],
            "_links": [],
        })
    return {
        "id": d["id"], "globalId": d["globalId"], "name": d["name"], "created": d["created"],
        "lastModified": d["lastModified"], "parentFolderId": d["parentFolderId"], "tags": d["tags"],
        "form": {"id": d["formId"], "globalId": f"FM{d['formId']}", "name": data.forms[d["formId"]]},
        "owner": OWNER, "signed": d.get("signed", False), "fields": fields,
        "_links": _self(base, f"/documents/{d['id']}"),
    }


def ser_inv_file(a: dict, base: str) -> dict:
    out = dict(a)
    out["_links"] = _self(base, f"/files/{a['id']}") + [
        {"link": f"{base}/files/{a['id']}/file", "rel": "enclosure"}]
    return out


def ser_summary(gid: str, data: MockData) -> dict:
    rec = data.record_by_global_id(gid)
    return {"id": rec["id"], "globalId": gid, "name": rec["name"], "type": rec["type"],
            "created": rec["created"], "lastModified": rec["lastModified"]}


def ser_fields(rec: dict, data: MockData, base: str) -> List[dict]:
    out = []
    for f in rec.get("fields", []):
        item = {k: f[k] for k in ("id", "globalId", "name", "type", "content")}
        att = f.get("attachment_id")
        item["attachment"] = ser_inv_file(data.inv_files[att], base) if att is not None else None
        out.append(item)
    return out


def _attachments(rec: dict, data: MockData, base: str) -> List[dict]:
    return [ser_inv_file(data.inv_files[i], base) for i in rec["attachment_ids"] if i in data.inv_files]


def _parent_containers(gid: Optional[str], data: MockData) -> List[dict]:
    chain = []
    while gid is not None:
        c = data.record_by_global_id(gid)
        chain.append({"id": c["id"], "globalId": gid, "name": c["name"], "cType": c["cType"]})
        gid = c.get("parentGlobalId")
    return chain


def ser_container(c: dict, data: MockData, base: str, include_content: bool) -> dict:
    content = c["content"]
    locations = []
    for idx, gid in enumerate(content):
        loc = {"id": c["id"] * 1000 + idx, "coordX": (idx % 2) + 1, "coordY": (idx // 2) + 1}
        if c["cType"] != "GRID":
            loc["coordX"], loc["coordY"] = 1, idx + 1
        loc["content"] = ser_summary(gid, data) if include_content else None
        locations.append(loc)
    counts = {"totalCount": len(content),
              "containerCount": sum(1 for g in content if g.startswith("IC")),
              "subSampleCount": sum(1 for g in content if g.startswith("SS"))}
    return {
        "id": c["id"], "globalId": c["globalId"], "name": c["name"], "type": "CONTAINER",
        "cType": c["cType"], "description": c["description"], "created": c["created"],
        "lastModified": c["lastModified"], "owner": OWNER, "tags": [], "extraFields": [],
        "barcode": None, "deleted": False, "gridLayout": c["gridLayout"],
        "canStoreContainers": c["canStoreContainers"], "canStoreSamples": c["canStoreSamples"],
        "locationsCount": len(content), "contentSummary": counts, "locations": locations,
        "parentContainers": _parent_containers(c["parentGlobalId"], data),
        "parentLocation": None, "attachments": _attachments(c, data, base),
        "_links": _self(base, f"/containers/{c['id']}"),
    }


def ser_subsample(ss: dict, data: MockData, base: str, brief: bool = False) -> dict:
    sample = data.samples[ss["sampleId"]]
    out = {
        "id": ss["id"], "globalId": ss["globalId"], "name": ss["name"], "type": "SUBSAMPLE",
        "created": ss["created"], "lastModified": ss["lastModified"], "owner": OWNER,
        "quantity": ss["quantity"], "tags": ss["tags"], "deleted": False,
        "storedInContainer": ss["parentGlobalId"] is not None,
        "parentContainers": _parent_containers(ss["parentGlobalId"], data),
        "parentLocation": None, "attachments": _attachments(ss, data, base),
        "_links": _self(base, f"/subSamples/{ss['id']}"),
    }
    if not brief:
        out["sample"] = {"id": sample["id"], "globalId": sample["globalId"], "name": sample["name"]}
        out["extraFields"] = []
        out["notes"] = []
    return out


def ser_sample(s: dict, data: MockData, base: str) -> dict:
    tpl = data.templates.get(s["templateId"]) if s["templateId"] else None
    return {
        "id": s["id"], "globalId": s["globalId"], "name": s["name"], "type": "SAMPLE",
        "description": s["description"], "created": s["created"], "lastModified": s["lastModified"],
        "owner": OWNER, "tags": s["tags"], "quantity": s["quantity"], "deleted": False,
        "templateId": s["templateId"],
        "template": ({"id": tpl["id"], "globalId": tpl["globalId"], "name": tpl["name"]} if tpl else None),
        "subSamplesCount": len(s["subsample_ids"]),
        "subSamples": [ser_subsample(data.subsamples[i], data, base, brief=True) for i in s["subsample_ids"]],
        "fields": ser_fields(s, data, base), "extraFields": [], "attachments": _attachments(s, data, base),
        "_links": _self(base, f"/samples/{s['id']}"),
    }


def ser_instrument(ins: dict, data: MockData, base: str) -> dict:
    return {
        "id": ins["id"], "globalId": ins["globalId"], "name": ins["name"], "type": "INSTRUMENT",
        "description": ins["description"], "created": ins["created"], "lastModified": ins["lastModified"],
        "owner": OWNER, "tags": ins["tags"], "deleted": False, "fields": [], "extraFields": [],
        "attachments": _attachments(ins, data, base),
        "_links": _self(base, f"/instruments/{ins['id']}"),
    }


def ser_template(t: dict, data: MockData, base: str) -> dict:
    return {
        "id": t["id"], "globalId": t["globalId"], "name": t["name"], "type": "SAMPLE_TEMPLATE",
        "description": t["description"], "created": t["created"], "lastModified": t["lastModified"],
        "owner": OWNER, "tags": t["tags"], "deleted": False, "defaultUnitId": t["defaultUnitId"],
        "subSampleAlias": t["subSampleAlias"], "fields": [], "extraFields": [],
        "attachments": _attachments(t, data, base),
        "_links": _self(base, f"/sampleTemplates/{t['id']}"),
    }
