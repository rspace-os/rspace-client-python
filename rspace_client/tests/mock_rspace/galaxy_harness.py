"""
Galaxy-like harness for the RSpace PyFilesystems.

Galaxy's PyFilesystem2FilesSource drives a filesystem with a very small surface:
    listing   fs.filterdir(path, namespaces=["details"], page=(start, end))
    walking   fs.walk(path, namespaces=["details"])
    download  fs.download(path, file_obj)
    upload    fs.upload(path, file_obj)
and turns each Info into a RemoteDirectory (name, uri, path) or a RemoteFile
(name, uri, path, size, ctime from info.created). This harness does exactly that
and prints the table Galaxy's remote-files browser would render, so you can see
what a Galaxy user would see without running Galaxy. It also reports how many
RSpace API calls each operation cost (via the mock server's /__mock/stats).

Examples (from the repo root):
    python -m rspace_client.tests.mock_rspace.galaxy_harness --embedded --fs gallery ls /
    python -m rspace_client.tests.mock_rspace.galaxy_harness --embedded --fs gallery walk /
    python -m rspace_client.tests.mock_rspace.galaxy_harness --embedded --fs inventory ls /IC200
    python -m rspace_client.tests.mock_rspace.galaxy_harness --embedded --fs gallery get /GF11/GL111 out.csv
    python -m rspace_client.tests.mock_rspace.galaxy_harness --embedded --fs inventory put /SS300/out.csv ./some.txt

Against an already running mock (or a real RSpace, at your own risk):
    python -m rspace_client.tests.mock_rspace.galaxy_harness --url http://127.0.0.1:8765 --fs gallery ls /

--fs rspace selects the unified RSpaceFilesystem (/gallery, /inventory, /workspace).
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from typing import Iterable, List, Optional

# make `rspace_client` importable when run as a script from anywhere in the repo
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import requests  # noqa: E402
from fs import errors as fs_errors  # noqa: E402
from fs.path import join as fs_join  # noqa: E402

URI_SCHEME = "gxfiles://rspace-mock"


# ------------------------------------------------------------------ FS factory

def build_fs(kind: str, url: str, api_key: str, writable: bool = False, allow_delete: bool = False,
             path_style: str = "name"):
    posture = dict(writable=writable, allow_delete=allow_delete, path_style=path_style)
    if kind == "gallery":
        from rspace_client.fs import GalleryFilesystem
        return GalleryFilesystem(url, api_key, **posture)
    if kind == "inventory":
        from rspace_client.fs import InventoryFilesystem
        return InventoryFilesystem(url, api_key, **posture)
    if kind == "rspace":
        from rspace_client.fs import RSpaceFilesystem
        return RSpaceFilesystem(url, api_key, **posture)
    sys.exit(f"unknown --fs {kind}")


# ------------------------------------------------------------------ stats

def api_calls(url: str) -> Optional[int]:
    try:
        return requests.get(f"{url}/__mock/stats", timeout=2).json()["requests"]
    except Exception:  # not the mock server
        return None


class CallCounter:
    def __init__(self, url: str):
        self.url, self.start = url, api_calls(url)

    def report(self, label: str) -> None:
        end = api_calls(self.url)
        if self.start is not None and end is not None:
            print(f"\n[{label}] RSpace API calls: {end - self.start}")


# ------------------------------------------------------------------ Galaxy view

def _fmt_time(dt: Optional[datetime]) -> str:
    return dt.strftime("%Y-%m-%d %H:%M") if dt else "-"


def _label(info) -> str:
    """Human-readable name from the custom `rspace` namespace, if the FS provides one."""
    rs = (info.raw or {}).get("rspace") or {}
    return str(rs.get("name", "")) if isinstance(rs, dict) else ""


def galaxy_entries(fs, path: str) -> List[dict]:
    """Mirror of PyFilesystem2FilesSource._list + _resource_info_to_dict."""
    entries = []
    for info in fs.filterdir(path, namespaces=["details"]):
        rel = fs_join(path, info.name)
        entry = {"name": info.name, "uri": URI_SCHEME + rel, "path": rel, "rspace_name": _label(info)}
        if info.is_dir:
            entry["class"] = "Directory"
        else:
            entry.update({"class": "File", "size": info.size, "ctime": _fmt_time(info.created)})
        entries.append(entry)
    return entries


def print_table(rows: Iterable[dict], path: str) -> None:
    rows = list(rows)
    print(f"Galaxy remote-files view of {path!r}  ({len(rows)} entries)")
    print(f"{'what Galaxy shows':<32} class      size      ctime             rspace name (not shown by Galaxy)")
    print("-" * 108)
    for r in rows:
        print(f"{r['name']:<32} {r['class']:<10} {str(r.get('size', '')):>8}  "
              f"{r.get('ctime', ''):<17} {r['rspace_name']}")
    if not rows:
        print("(empty)")


# ------------------------------------------------------------------ commands

def cmd_ls(fs, url, path):
    c = CallCounter(url)
    try:
        print_table(galaxy_entries(fs, path), path)
    except fs_errors.ResourceNotFound:
        print(f"{path!r}: not found")
    c.report("ls")


def cmd_walk(fs, url, path, max_depth):
    c = CallCounter(url)
    print(f"walk {path!r} (Galaxy recursive listing, depth<={max_depth})")
    try:
        for dir_path, dirs, files in fs.walk(path, namespaces=["details"], max_depth=max_depth):
            depth = dir_path.rstrip("/").count("/")
            pad = "  " * depth
            print(f"{pad}{dir_path or '/'}")
            for d in dirs:
                print(f"{pad}  [D] {d.name:<22} {_label(d)}")
            for f in files:
                print(f"{pad}  [F] {f.name:<22} {str(f.size):>7}  {_fmt_time(f.created)}  {_label(f)}")
    except fs_errors.ResourceNotFound:
        print(f"{path!r}: not found")
    c.report("walk")


def cmd_get(fs, url, path, out):
    c = CallCounter(url)
    with open(out, "wb") as fh:
        fs.download(path, fh)
    print(f"downloaded {path} -> {out} ({os.path.getsize(out)} bytes)")
    c.report("get")


def cmd_put(fs, url, path, local):
    """`path` is the destination FILE path (for example /SS300/out.csv), not the record."""
    c = CallCounter(url)
    try:
        with open(local, "rb") as fh:
            fs.upload(path, fh)
    except fs_errors.ResourceReadOnly:
        raise
    except fs_errors.FSError as e:
        print(f"{path!r}: {e}")
    else:
        print(f"uploaded {local} -> {path}")
    c.report("put")


def cmd_info(fs, url, path):
    c = CallCounter(url)
    info = fs.getinfo(path, namespaces=["details"])
    print(f"{path}: is_dir={info.is_dir} size={info.size} created={_fmt_time(info.created)} name={info.name!r}")
    print("raw:", info.raw)
    c.report("info")


def cmd_stats(url):
    try:
        print(requests.get(f"{url}/__mock/stats", timeout=2).json())
    except Exception as e:
        print(f"no mock stats available at {url}: {e}")


# ------------------------------------------------------------------ main

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Drive an RSpace PyFilesystem the way Galaxy does")
    ap.add_argument("--url", default=os.environ.get("RSPACE_URL", "http://127.0.0.1:8765"))
    ap.add_argument("--api-key", default=os.environ.get("RSPACE_API_KEY", "mock-key"))
    ap.add_argument("--fs", choices=["gallery", "inventory", "rspace"], default="gallery")
    ap.add_argument("--embedded", action="store_true",
                    help="start the mock server in-process on a free port (ignores --url)")
    ap.add_argument("--writable", action="store_true", help="allow put / makedir (default: read-only)")
    ap.add_argument("--allow-delete", action="store_true", help="allow remove / removedir")
    ap.add_argument("--path-style", choices=["name", "labelled", "id"], default="name",
                    help="'name' shows record names (default); 'labelled' shows 'Name [GID]'; "
                         "'id' shows bare global IDs")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("ls").add_argument("path", nargs="?", default="/")
    p = sub.add_parser("walk")
    p.add_argument("path", nargs="?", default="/")
    p.add_argument("--max-depth", type=int, default=3)
    p = sub.add_parser("get"); p.add_argument("path"); p.add_argument("out")
    p = sub.add_parser("put"); p.add_argument("path"); p.add_argument("local")
    sub.add_parser("info").add_argument("path")
    sub.add_parser("stats")
    args = ap.parse_args(argv)

    url = args.url
    if args.embedded:
        try:
            from rspace_client.tests.mock_rspace.server import run_in_thread
        except ImportError:
            from server import run_in_thread  # type: ignore  # run as a plain script from this directory
        _, url = run_in_thread()
        print(f"(embedded mock RSpace at {url})")

    if args.cmd == "stats":
        cmd_stats(url)
        return 0

    setup = CallCounter(url)
    fs = build_fs(args.fs, url, args.api_key, args.writable, args.allow_delete, args.path_style)
    setup.report(f"constructing {type(fs).__name__}")
    print()

    try:
        if args.cmd == "ls":
            cmd_ls(fs, url, args.path)
        elif args.cmd == "walk":
            cmd_walk(fs, url, args.path, args.max_depth)
        elif args.cmd == "get":
            cmd_get(fs, url, args.path, args.out)
        elif args.cmd == "put":
            cmd_put(fs, url, args.path, args.local)
        elif args.cmd == "info":
            cmd_info(fs, url, args.path)
    except fs_errors.ResourceReadOnly as e:
        print(f"refused: {e}\n(the filesystem is read-only by default; add --writable, and --allow-delete for removals)")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
