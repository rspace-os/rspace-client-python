"""PROTOTYPE, not part of the package: the Gallery branch re-expressed as an fsspec
filesystem, plus a minimal mount dispatcher (fsspec has no MountFS). Written during the
2026-09-21 spike and verified against the mock server and Galaxy's FsspecFilesSource.
Delete once rspace_client.fs is implemented on fsspec. Lessons it encodes:

* ``_ls_from_cache`` hands back a directory's own entry from the parent's cache, so read
  ``dircache`` directly;
* the default ``info()`` falls back to ``ls(path)``, which recurses for an unknown path, so
  ``info`` resolves from the parent listing only;
* RSpace takes one multipart body per upload, so the buffered file keeps everything until
  final and uploads in ``commit()`` (or on final flush under autocommit), which makes
  fsspec transactions work;
* folder-tree items carry no size; Galaxy needs ``int(size)``, so the top-up is a keyword;
* protocol names must be valid URI schemes for universal_pathlib (no ``-``);
* ``cachable = False`` because instances hold an API key.
"""
from __future__ import annotations

import io
from typing import Optional

import fsspec
from fsspec.spec import AbstractBufferedFile, AbstractFileSystem

from rspace_client.eln import eln

GALLERY = "Gallery"
FOLDER_PREFIXES = ("GF", "FL")


def _to_epoch(value):
    from datetime import datetime, timezone
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return float(value) / 1000.0 if value > 1e11 else float(value)
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def _stream_pages(client, first_page, key):
    page = first_page
    while True:
        yield from page.get(key, [])
        next_link = next((l["link"] for l in page.get("_links", []) if l.get("rel") == "next"), None)
        if not next_link:
            return
        page = client.retrieve_api_results(next_link)


class RSpaceUploadFile(AbstractBufferedFile):
    def _initiate_upload(self):
        pass

    def _upload_chunk(self, final=False):
        if final and self.autocommit:
            self._send()
        return False  # keep buffering; one body per upload

    def commit(self):
        self._send()

    def discard(self):
        self.buffer = io.BytesIO()

    def _send(self):
        self.buffer.seek(0)
        self.buffer.name = self.path.rsplit("/", 1)[-1]
        folder_id = self.fs._folder_id(self.fs._parent(self.path))
        self.fs._last_upload = self.fs.client.upload_file(self.buffer, folder_id=folder_id)
        self.fs.invalidate_cache(self.fs._parent(self.path))


class GalleryFileSystem(AbstractFileSystem):
    protocol = "rspacegallery"
    cachable = False

    def __init__(self, server=None, api_key=None, *, client=None, writable=False,
                 allow_delete=False, page_size=100, fetch_sizes=False, **storage_options):
        super().__init__(**storage_options)  # gives self.dircache
        self.client = client or eln.ELNClient(server, api_key)
        self.writable, self.allow_delete = writable, allow_delete
        self.page_size, self.fetch_sizes = page_size, fetch_sizes
        self._gallery_id: Optional[int] = None
        self._last_upload = None

    @classmethod
    def _strip_protocol(cls, path):
        return super()._strip_protocol(path).strip("/")

    def _records(self, folder_id):
        try:
            first = self.client.list_folder_tree(folder_id, page_size=self.page_size)
        except TypeError:  # rspace-client < 2.8 has no page_size
            first = self.client.list_folder_tree(folder_id)
        return _stream_pages(self.client, first, "records")

    @property
    def gallery_id(self):
        if self._gallery_id is None:
            self._gallery_id = next(int(r["id"]) for r in self._records(None) if r["name"] == GALLERY)
        return self._gallery_id

    def _entry(self, parent, record):
        is_dir = record["globalId"][:2] in FOLDER_PREFIXES
        return {"name": f"{parent}/{record['name']}".strip("/"),
                "type": "directory" if is_dir else "file", "size": record.get("size"),
                # Galaxy reads only mtime/modified/LastModified for its time column and RSpace
                # files carry no lastModified, so fall back to created there
                "mtime": _to_epoch(record.get("lastModified") or record.get("created")),
                "created": _to_epoch(record.get("created")),
                "globalId": record["globalId"], "rspace": record}

    def _folder_id(self, path):
        path = self._strip_protocol(path)
        if not path:
            return self.gallery_id
        info = self.info(path)
        if info["type"] != "directory":
            raise NotADirectoryError(path)
        return int(info["globalId"][2:])

    def ls(self, path, detail=True, refresh=False, **kwargs):
        path = self._strip_protocol(path)
        out = None if refresh else self.dircache.get(path)
        if out is None:
            out, seen = [], set()
            for record in self._records(self._folder_id(path)):
                if self.fetch_sizes and record["globalId"][:2] == "GL" and record.get("size") is None:
                    record = self.client.get_file_info(record["id"])
                e = self._entry(path, record)
                if e["name"] in seen:
                    e["name"] += f" [{e['globalId']}]"
                seen.add(e["name"])
                out.append(e)
            self.dircache[path] = out
        return out if detail else [o["name"] for o in out]

    def info(self, path, **kwargs):
        path = self._strip_protocol(path)
        if not path:
            return {"name": "", "type": "directory", "size": None, "globalId": None}
        hits = [e for e in self.ls(self._parent(path), **kwargs) if e["name"] == path]
        if not hits:
            raise FileNotFoundError(path)
        return hits[0]

    def cat_file(self, path, start=None, end=None, **kwargs):
        info = self.info(path)
        if info["type"] != "file":
            raise IsADirectoryError(path)
        buf = io.BytesIO()
        self.client.download_file(info["globalId"][2:], buf)
        data = buf.getvalue()
        return data[start:end] if (start is not None or end is not None) else data

    def _open(self, path, mode="rb", block_size=None, autocommit=True, cache_options=None, **kwargs):
        if mode == "rb":
            return io.BytesIO(self.cat_file(path))
        if mode in ("wb", "xb"):
            if not self.writable:
                raise PermissionError(f"{path}: filesystem opened read-only; pass writable=True")
            return RSpaceUploadFile(self, self._strip_protocol(path), mode="wb",
                                    block_size=2 ** 62, autocommit=autocommit)
        raise ValueError(f"unsupported mode {mode!r}")

    def mkdir(self, path, create_parents=True, **kwargs):
        if not self.writable:
            raise PermissionError(f"{path}: read-only")
        path = self._strip_protocol(path)
        parent, name = self._parent(path), path.rsplit("/", 1)[-1]
        if any(e["name"] == path and e["type"] == "directory" for e in self.ls(parent)):
            raise FileExistsError(path)
        self.client.create_folder(name, self._folder_id(parent))
        self.invalidate_cache(parent)

    def rmdir(self, path):
        if not self.allow_delete:
            raise PermissionError(f"{path}: deletes disabled; pass allow_delete=True")
        self.client.delete_folder(self.info(path)["globalId"][2:])
        self.invalidate_cache(self._parent(path))

    def rm_file(self, path):
        raise NotImplementedError("the RSpace API cannot delete Gallery files")


class MountFileSystem(AbstractFileSystem):
    """First path segment picks a branch filesystem."""
    protocol = "rspace"
    cachable = False

    def __init__(self, mounts: dict, **storage_options):
        super().__init__(**storage_options)
        self.mounts = mounts

    @classmethod
    def _strip_protocol(cls, path):
        return super()._strip_protocol(path).strip("/")

    def _route(self, path):
        path = self._strip_protocol(path)
        head, _, rest = path.partition("/")
        if head not in self.mounts:
            raise FileNotFoundError(path)
        return head, self.mounts[head], rest

    @staticmethod
    def _lift(head, entry):
        e = dict(entry)
        e["name"] = f"{head}/{e['name']}".rstrip("/")
        return e

    def ls(self, path, detail=True, **kwargs):
        path = self._strip_protocol(path)
        if not path:
            out = [{"name": m, "type": "directory", "size": None} for m in self.mounts]
        else:
            head, fs, rest = self._route(path)
            out = [self._lift(head, e) for e in fs.ls(rest, detail=True, **kwargs)]
        return out if detail else [o["name"] for o in out]

    def info(self, path, **kwargs):
        path = self._strip_protocol(path)
        if not path:
            return {"name": "", "type": "directory", "size": None}
        head, fs, rest = self._route(path)
        if not rest:
            return {"name": head, "type": "directory", "size": None}
        return self._lift(head, fs.info(rest, **kwargs))

    def _open(self, path, mode="rb", **kwargs):
        _, fs, rest = self._route(path)
        return fs._open(rest, mode=mode, **kwargs)

    def mkdir(self, path, **kwargs):
        _, fs, rest = self._route(path)
        if not rest:
            raise PermissionError("the top level is fixed")
        fs.mkdir(rest, **kwargs)

    def rmdir(self, path):
        _, fs, rest = self._route(path)
        fs.rmdir(rest)

    def rm_file(self, path):
        _, fs, rest = self._route(path)
        fs.rm_file(rest)


fsspec.register_implementation("rspacegallery", GalleryFileSystem, clobber=True)
