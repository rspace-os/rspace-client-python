"""
Drive Galaxy's own RSpace file source against this client, without running Galaxy.

Galaxy ships a ``rspace`` FilesSource plugin (galaxy/files/sources/rspace.py) built on
``rspace_client.eln.fs.GalleryFilesystem``. This script loads that real plugin through
Galaxy's real ``ConfiguredFileSources`` machinery and lists paths through it, so changes
to this library can be checked against the actual consumer in seconds.

Setup (once):

    python3 -m venv .galaxy-venv
    .galaxy-venv/bin/pip install galaxy-files -e .

Run against the bundled mock RSpace (offline):

    .galaxy-venv/bin/python tools/galaxy/check_plugin.py --mock

Run against a real RSpace (RSPACE_URL / RSPACE_API_KEY, or .env):

    .galaxy-venv/bin/python tools/galaxy/check_plugin.py / /GF8

What to look for: entries carry the RSpace *name* while the URI uses the global ID, and
files must have an integer ``size`` (Galaxy's RemoteFile model rejects null).
"""
import argparse
import os
import sys

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="*", default=["/"], help="paths to list (default: /)")
    ap.add_argument("--mock", action="store_true", help="start the bundled mock RSpace server and use it")
    ap.add_argument("--url", default=os.getenv("RSPACE_URL"))
    ap.add_argument("--api-key", default=os.getenv("RSPACE_API_KEY"))
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--recursive", action="store_true")
    args = ap.parse_args()

    try:
        from galaxy.files import ConfiguredFileSources, ConfiguredFileSourcesConf
        from galaxy.files.models import FileSourcePluginsConfig
    except ImportError:
        sys.exit("galaxy-files is not installed in this interpreter: pip install galaxy-files")

    if args.mock:
        from rspace_client.tests.mock_rspace.server import run_in_thread
        _, args.url = run_in_thread()
        args.api_key = "mock-key"
        print(f"(embedded mock RSpace at {args.url})")
    if not args.url or not args.api_key:
        try:
            from dotenv import load_dotenv
            load_dotenv(os.path.join(REPO_ROOT, ".env"))
            args.url = args.url or os.getenv("RSPACE_URL")
            args.api_key = args.api_key or os.getenv("RSPACE_API_KEY")
        except ImportError:
            pass
    if not args.url or not args.api_key:
        sys.exit("set RSPACE_URL and RSPACE_API_KEY (or pass --mock)")

    conf = [{"type": "rspace", "id": "rspace_check", "label": "RSpace",
             "endpoint": args.url, "api_key": args.api_key, "writable": True}]
    sources = ConfiguredFileSources(FileSourcePluginsConfig(), ConfiguredFileSourcesConf(conf_dict=conf))
    source = sources.get_file_source_path("gxfiles://rspace_check").file_source

    import rspace_client
    print(f"plugin  : {type(source).__name__} (writable={source.get_writable()})")
    print(f"client  : {os.path.dirname(rspace_client.__file__)}")

    failures = 0
    for path in args.paths:
        try:
            entries, count = source.list(path, recursive=args.recursive, limit=args.limit)
        except Exception as exc:  # a broken plugin contract shows up here
            failures += 1
            print(f"\n{path}\n   ERROR {type(exc).__name__}: {str(exc)[:400]}")
            continue
        print(f"\n{path}   ({count} entries)")
        print(f"   {'class':<10} {'name (what Galaxy shows)':<38} {'size':>9}  uri")
        for entry in entries:
            d = entry.model_dump()
            print(f"   {d.get('class_', '?'):<10} {str(d.get('name')):<38} {str(d.get('size', '-')):>9}  {d.get('uri')}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
