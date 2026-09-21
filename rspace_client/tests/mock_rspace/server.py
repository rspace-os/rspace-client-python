"""
A small, dependency-free mock of the RSpace ELN (/api/v1) and Inventory
(/api/inventory/v1) REST APIs, covering just the endpoints the PyFilesystem
implementations use. Backed by the in-memory dataset in fixtures.py.

Run standalone:
    python -m rspace_client.tests.mock_rspace.server --port 8765

Or embed in a test / the harness:
    from rspace_client.tests.mock_rspace.server import run_in_thread
    server, url = run_in_thread()          # url like http://127.0.0.1:54321

Control endpoints (not part of RSpace, not counted in stats):
    GET  /__mock/stats   -> {"requests": N, "by_path": {...}}
    POST /__mock/reset   -> reset dataset and counters

Behavioural notes that mirror the real client's expectations:
  * every JSON response (including errors) carries Content-Type application/json,
    because ClientBase._handle_response indexes that header on failure;
  * DELETE returns 204 with no body and no JSON content type, otherwise the
    client would try to .json() an empty body;
  * paginated listings key the collection by endpoint name (containers, samples,
    templates) and emit absolute _links (self/next/prev) on the request's origin,
    which ClientBase._stream follows.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlencode, urlparse

try:  # package import (python -m rspace_client.tests.mock_rspace.server, or from tests)
    from . import fixtures as fx
except ImportError:  # run as a plain script from its own directory
    import fixtures as fx  # type: ignore

ELN_PREFIX = "/api/v1"
INV_PREFIX = "/api/inventory/v1"

Route = Tuple[str, "re.Pattern[str]", Callable]


class ApiError(Exception):
    def __init__(self, status: int, message: str, errors: Optional[List[str]] = None):
        super().__init__(message)
        self.status, self.message, self.errors = status, message, errors or []


def parse_multipart(content_type: str, body: bytes) -> Dict[str, Tuple[Optional[str], bytes, str]]:
    """Byte-exact multipart/form-data parser. Returns name -> (filename, bytes, part content-type)."""
    m = re.search(r'boundary="?([^";]+)"?', content_type or "")
    if not m:
        raise ApiError(400, "multipart/form-data with boundary expected")
    delim = b"--" + m.group(1).encode()
    parts: Dict[str, Tuple[Optional[str], bytes, str]] = {}
    for chunk in body.split(delim):
        if chunk.startswith(b"\r\n"):
            chunk = chunk[2:]
        if not chunk or chunk.startswith(b"--"):
            continue
        header_blob, _, payload = chunk.partition(b"\r\n\r\n")
        if payload.endswith(b"\r\n"):
            payload = payload[:-2]
        headers: Dict[str, str] = {}
        for line in header_blob.split(b"\r\n"):
            k, _, v = line.partition(b":")
            headers[k.strip().lower().decode()] = v.strip().decode(errors="replace")
        disp = headers.get("content-disposition", "")
        name = re.search(r'name="([^"]*)"', disp)
        filename = re.search(r'filename="([^"]*)"', disp)
        parts[name.group(1) if name else ""] = (
            filename.group(1) if filename else None, payload,
            headers.get("content-type", "application/octet-stream"))
    return parts


class MockRSpaceServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    #: What the server writes into its ``_links``. A real RSpace advertises its own configured
    #: base URL, which is often not the address the client used (proxy, container, port-forward),
    #: so the mock does the same and clients have to cope with it.
    advertised_base = "http://rspace.advertised.example:8080"

    def __init__(self, address: Tuple[str, int], data: Optional[fx.MockData] = None, verbose: bool = False):
        super().__init__(address, MockRSpaceHandler)
        self.data = data or fx.MockData()
        self.verbose = verbose
        self.stats_lock = threading.Lock()
        self.stats: Dict = {"requests": 0, "by_path": {}}

    @property
    def url(self) -> str:
        host, port = self.server_address[:2]
        return f"http://{host}:{port}"

    def reset(self) -> None:
        with self.data.lock:
            self.data.reset()
        with self.stats_lock:
            self.stats = {"requests": 0, "by_path": {}}


class MockRSpaceHandler(BaseHTTPRequestHandler):
    server_version = "MockRSpace/0.1"
    server: MockRSpaceServer  # type: ignore[assignment]

    # ------------------------------------------------------------ plumbing

    def log_message(self, fmt, *args):  # quiet unless --verbose
        if self.server.verbose:
            super().log_message(fmt, *args)

    def _host_base(self) -> str:
        # deliberately not the Host header: see MockRSpaceServer.advertised_base
        return self.server.advertised_base

    def _send_json(self, obj, status: int = 200) -> None:
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_bytes(self, data: bytes, content_type: str, filename: Optional[str] = None) -> None:
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        if filename:
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.end_headers()
        self.wfile.write(data)

    def _send_no_content(self) -> None:
        self.send_response(204)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(length) if length else b""

    def _json_body(self) -> dict:
        raw = self._read_body()
        try:
            return json.loads(raw or b"{}")
        except json.JSONDecodeError:
            raise ApiError(400, "request body is not valid JSON")

    def _count(self, path: str) -> None:
        with self.server.stats_lock:
            self.server.stats["requests"] += 1
            key = re.sub(r"/\d+", "/{id}", path)
            self.server.stats["by_path"][key] = self.server.stats["by_path"].get(key, 0) + 1

    # ------------------------------------------------------------ dispatch

    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def do_PUT(self):
        self._dispatch("PUT")

    def do_DELETE(self):
        self._dispatch("DELETE")

    def _dispatch(self, method: str) -> None:
        parsed = urlparse(self.path)
        path, query = parsed.path, {k: v[0] for k, v in parse_qs(parsed.query).items()}
        try:
            if path.startswith("/__mock/"):
                return self._mock_control(method, path)
            self._count(path)
            if not self.headers.get("apiKey"):
                raise ApiError(401, "Unauthorized: apiKey header is missing")
            for prefix, routes in ((INV_PREFIX, INV_ROUTES), (ELN_PREFIX, ELN_ROUTES)):
                if path.startswith(prefix + "/") or path == prefix:
                    sub = path[len(prefix):] or "/"
                    for m, pattern, handler in routes:
                        match = pattern.fullmatch(sub)
                        if m == method and match:
                            base = self._host_base() + prefix
                            return handler(self, base, query, **match.groupdict())
                    raise ApiError(404, f"no mock route for {method} {path}")
            raise ApiError(404, f"unknown path {path}")
        except ApiError as e:
            self._send_json({"status": e.status, "message": e.message, "errors": e.errors}, e.status)
        except KeyError as e:
            self._send_json({"status": 404, "message": f"resource not found: {e}", "errors": []}, 404)
        except ValueError as e:
            self._send_json({"status": 400, "message": str(e), "errors": []}, 400)

    def _mock_control(self, method: str, path: str) -> None:
        if path == "/__mock/stats" and method == "GET":
            with self.server.stats_lock:
                return self._send_json(json.loads(json.dumps(self.server.stats)))
        if path == "/__mock/reset" and method == "POST":
            self.server.reset()
            return self._send_json({"reset": True})
        raise ApiError(404, f"unknown control endpoint {path}")

    # ------------------------------------------------------------ helpers

    def _paginate(self, items: List[dict], query: dict, base: str, endpoint: str, key: str) -> dict:
        page = int(query.get("pageNumber", 0))
        size = max(1, int(query.get("pageSize", 20)))
        total = len(items)
        start = page * size
        chunk = items[start:start + size]

        def link(p: int, rel: str) -> dict:
            q = dict(query)
            q["pageNumber"], q["pageSize"] = p, size
            return {"link": f"{base}/{endpoint}?{urlencode(q)}", "rel": rel}

        links = [link(page, "self")]
        if start + size < total:
            links.append(link(page + 1, "next"))
        if page > 0:
            links.append(link(page - 1, "prev"))
        return {key: chunk, "totalHits": total, "pageNumber": page, "_links": links}


# ================================================================ ELN routes

def eln_status(h: MockRSpaceHandler, base, query):
    h._send_json({"message": "OK", "rspaceVersion": "mock-0.1"})


def eln_folder_tree(h: MockRSpaceHandler, base, query, id=None):
    data = h.server.data
    fid = int(id) if id is not None else data.home_id()
    if fid not in data.folders:
        raise KeyError(f"FL{fid}")
    gids = list(data.children.get(fid, []))
    types = query.get("typesToInclude")
    if types:
        wanted = {t.strip().lower() for t in types.split(",")}
        keep = {"folder": ("FL", "GF"), "notebook": ("NB",), "document": ("SD",)}
        allowed = tuple(p for t in wanted for p in keep.get(t, ()))
        gids = [g for g in gids if g.startswith(allowed)]
    records = [fx.ser_tree_item(g, data, base) for g in gids]
    out = h._paginate(records, query, base, f"folders/tree/{fid}", "records")
    out["folderId"] = fid
    h._send_json(out)


def eln_get_folder(h: MockRSpaceHandler, base, query, id):
    h._send_json(fx.ser_folder(h.server.data.folders[int(id)], base))


def eln_create_folder(h: MockRSpaceHandler, base, query):
    body = h._json_body()
    if not body.get("name"):
        raise ApiError(400, "name is required", ["name: must not be empty"])
    with h.server.data.lock:
        f = h.server.data.add_folder(body["name"], body.get("parentFolderId"), bool(body.get("notebook")))
    h._send_json(fx.ser_folder(f, base), 201)


def eln_delete_folder(h: MockRSpaceHandler, base, query, id):
    data = h.server.data
    with data.lock:
        f = data.folders[int(id)]
        if f.get("system"):
            raise ApiError(403, f"{f['globalId']} is a system folder and cannot be deleted")
        data.remove_folder(int(id))
    h._send_no_content()


def eln_get_file(h: MockRSpaceHandler, base, query, id):
    h._send_json(fx.ser_gallery_file(h.server.data.gallery_files[int(id)], base))


def eln_download_file(h: MockRSpaceHandler, base, query, id):
    g = h.server.data.gallery_files[int(id)]
    h._send_bytes(h.server.data.blobs[g["globalId"]], g["contentType"], g["name"])


def eln_upload_file(h: MockRSpaceHandler, base, query):
    parts = parse_multipart(h.headers.get("Content-Type", ""), h._read_body())
    if "file" not in parts:
        raise ApiError(400, "multipart field 'file' is required")
    filename, content, ctype = parts["file"]
    folder = parts.get("folderId")
    folder_id = int(folder[1].decode()) if folder and folder[1] else None
    caption = parts["caption"][1].decode() if "caption" in parts else ""
    with h.server.data.lock:
        name = filename or f"upload-{h.server.data.new_id()}.bin"
        g = h.server.data.add_gallery_file(name, folder_id, content,
                                           None if ctype == "application/octet-stream" else ctype, caption)
    h._send_json(fx.ser_gallery_file(g, base), 201)


def eln_get_document(h: MockRSpaceHandler, base, query, id):
    d = h.server.data.documents[int(id)]
    h._send_json(fx.ser_document(d, h.server.data, base))


def eln_update_document(h: MockRSpaceHandler, base, query, id):
    body = h._json_body()
    with h.server.data.lock:
        d = h.server.data.update_document(int(id), body)
    h._send_json(fx.ser_document(d, h.server.data, base))


ELN_ROUTES: List[Route] = [
    ("GET", re.compile(r"/status"), eln_status),
    ("GET", re.compile(r"/folders/tree"), eln_folder_tree),
    ("GET", re.compile(r"/folders/tree/(?P<id>\d+)"), eln_folder_tree),
    ("GET", re.compile(r"/folders/(?P<id>\d+)"), eln_get_folder),
    ("POST", re.compile(r"/folders"), eln_create_folder),
    ("DELETE", re.compile(r"/folders/(?P<id>\d+)"), eln_delete_folder),
    ("GET", re.compile(r"/files/(?P<id>\d+)"), eln_get_file),
    ("GET", re.compile(r"/files/(?P<id>\d+)/file"), eln_download_file),
    ("POST", re.compile(r"/files"), eln_upload_file),
    ("GET", re.compile(r"/documents/(?P<id>\d+)"), eln_get_document),
    ("PUT", re.compile(r"/documents/(?P<id>\d+)"), eln_update_document),
]


# ============================================================ Inventory routes

def _truthy(v: Optional[str]) -> bool:
    return str(v).lower() in ("true", "1", "yes")


def inv_workbenches(h: MockRSpaceHandler, base, query):
    data = h.server.data
    h._send_json({"containers": [fx.ser_container(b, data, base, include_content=False) for b in data.benches()]})


def inv_list_containers(h: MockRSpaceHandler, base, query):
    data = h.server.data
    items = [fx.ser_container(c, data, base, include_content=False) for c in data.top_level_containers()]
    h._send_json(h._paginate(items, query, base, "containers", "containers"))


def inv_get_container(h: MockRSpaceHandler, base, query, id):
    data = h.server.data
    container = data.containers[int(id)]
    if container["cType"] == "WORKBENCH":  # mirrors the real server
        raise ApiError(422, f"Container with id {id} is a workbench", [f"Container with id {id} is a workbench"])
    h._send_json(fx.ser_container(container, data, base, _truthy(query.get("includeContent"))))


def inv_get_workbench(h: MockRSpaceHandler, base, query, id):
    data = h.server.data
    bench = data.containers[int(id)]
    if bench["cType"] != "WORKBENCH":
        raise ApiError(404, f"no workbench with id {id}")
    h._send_json(fx.ser_container(bench, data, base, _truthy(query.get("includeContent"))))


def inv_list_samples(h: MockRSpaceHandler, base, query):
    data = h.server.data
    items = [fx.ser_sample(s, data, base) for s in data.samples.values()]
    h._send_json(h._paginate(items, query, base, "samples", "samples"))


def inv_get_sample(h: MockRSpaceHandler, base, query, id):
    data = h.server.data
    h._send_json(fx.ser_sample(data.samples[int(id)], data, base))


def inv_get_subsample(h: MockRSpaceHandler, base, query, id):
    data = h.server.data
    h._send_json(fx.ser_subsample(data.subsamples[int(id)], data, base))


def inv_list_templates(h: MockRSpaceHandler, base, query):
    data = h.server.data
    items = [fx.ser_template(t, data, base) for t in data.templates.values()]
    h._send_json(h._paginate(items, query, base, "sampleTemplates", "templates"))


def inv_get_template(h: MockRSpaceHandler, base, query, id):
    data = h.server.data
    h._send_json(fx.ser_template(data.templates[int(id)], data, base))


def inv_get_instrument(h: MockRSpaceHandler, base, query, id):
    data = h.server.data
    h._send_json(fx.ser_instrument(data.instruments[int(id)], data, base))


def inv_get_file(h: MockRSpaceHandler, base, query, id):
    h._send_json(fx.ser_inv_file(h.server.data.inv_files[int(id)], base))


def inv_download_file(h: MockRSpaceHandler, base, query, id):
    a = h.server.data.inv_files[int(id)]
    h._send_bytes(h.server.data.blobs[a["globalId"]], a["contentMimeType"], a["name"])


def inv_upload_file(h: MockRSpaceHandler, base, query):
    parts = parse_multipart(h.headers.get("Content-Type", ""), h._read_body())
    if "file" not in parts or "fileSettings" not in parts:
        raise ApiError(400, "multipart fields 'file' and 'fileSettings' are required")
    filename, content, ctype = parts["file"]
    try:
        settings = json.loads(parts["fileSettings"][1].decode())
    except json.JSONDecodeError:
        raise ApiError(400, "fileSettings must be JSON")
    parent = settings.get("parentGlobalId")
    if not parent:
        raise ApiError(400, "fileSettings.parentGlobalId is required")
    with h.server.data.lock:
        name = filename or f"upload-{h.server.data.new_id()}.bin"
        a = h.server.data.add_inv_file(parent, name, content,
                                       None if ctype == "application/octet-stream" else ctype)
    h._send_json(fx.ser_inv_file(a, base), 201)


def inv_attach_gallery_file(h: MockRSpaceHandler, base, query):
    body = h._json_body()
    parent, media = body.get("parentGlobalId"), body.get("mediaFileGlobalId")
    if not parent or not media:
        raise ApiError(400, "parentGlobalId and mediaFileGlobalId are required")
    with h.server.data.lock:
        try:
            a = h.server.data.link_gallery_file(parent, media)
        except ValueError as exc:
            raise ApiError(422, str(exc))
    h._send_json(fx.ser_inv_file(a, base), 201)


def inv_delete_file(h: MockRSpaceHandler, base, query, id):
    with h.server.data.lock:
        h.server.data.remove_inv_file(int(id))
    h._send_no_content()


INV_ROUTES: List[Route] = [
    ("GET", re.compile(r"/workbenches"), inv_workbenches),
    ("GET", re.compile(r"/workbenches/(?P<id>\d+)"), inv_get_workbench),
    ("GET", re.compile(r"/containers"), inv_list_containers),
    ("GET", re.compile(r"/containers/(?P<id>\d+)"), inv_get_container),
    ("GET", re.compile(r"/samples"), inv_list_samples),
    ("GET", re.compile(r"/samples/(?P<id>\d+)"), inv_get_sample),
    ("GET", re.compile(r"/subSamples/(?P<id>\d+)"), inv_get_subsample),
    ("GET", re.compile(r"/sampleTemplates"), inv_list_templates),
    ("GET", re.compile(r"/sampleTemplates/(?P<id>\d+)"), inv_get_template),
    ("GET", re.compile(r"/instruments/(?P<id>\d+)"), inv_get_instrument),
    ("GET", re.compile(r"/files/(?P<id>\d+)"), inv_get_file),
    ("GET", re.compile(r"/files/(?P<id>\d+)/file"), inv_download_file),
    ("POST", re.compile(r"/files"), inv_upload_file),
    ("POST", re.compile(r"/attachments"), inv_attach_gallery_file),
    ("DELETE", re.compile(r"/files/(?P<id>\d+)"), inv_delete_file),
]


# ================================================================ entry points

def make_server(host: str = "127.0.0.1", port: int = 8765, verbose: bool = False) -> MockRSpaceServer:
    return MockRSpaceServer((host, port), verbose=verbose)


def run_in_thread(host: str = "127.0.0.1", port: int = 0, verbose: bool = False) -> Tuple[MockRSpaceServer, str]:
    """Start the server on a background daemon thread. port=0 picks a free port. Returns (server, url)."""
    server = make_server(host, port, verbose)
    threading.Thread(target=server.serve_forever, name="mock-rspace", daemon=True).start()
    return server, server.url


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Mock RSpace ELN + Inventory API server")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--verbose", "-v", action="store_true", help="log every request")
    args = ap.parse_args(argv)
    server = make_server(args.host, args.port, args.verbose)
    print(f"Mock RSpace listening on {server.url}  (ELN: {ELN_PREFIX}, Inventory: {INV_PREFIX})")
    print("Use any non-empty apiKey. Ctrl-C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
