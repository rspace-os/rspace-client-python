"""
Browse RSpace as a filesystem: Gallery, Inventory and ELN Workspace under one mount.

    export RSPACE_URL=https://my.rspace.host RSPACE_API_KEY=...
    python examples/pyfilesystem_browse.py

    python examples/pyfilesystem_browse.py --mock      # offline, against the bundled mock server

Shows the top level, prints a tree of the Workspace, downloads a file found in a document
field, and (with --writable) uploads a file into that field.
"""
import argparse
import io
import os
import sys

from rspace_client.fs import RSpaceFilesystem, print_tree


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=os.getenv("RSPACE_URL"))
    ap.add_argument("--api-key", default=os.getenv("RSPACE_API_KEY"))
    ap.add_argument("--mock", action="store_true", help="start the bundled mock RSpace server and use it")
    ap.add_argument("--writable", action="store_true", help="also demonstrate an upload into a document field")
    args = ap.parse_args()

    if args.mock:
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
        from rspace_client.tests.mock_rspace.server import run_in_thread
        _, args.url = run_in_thread()
        args.api_key = "mock-key"
    if not args.url or not args.api_key:
        sys.exit("set RSPACE_URL and RSPACE_API_KEY (or pass --mock)")

    rspace = RSpaceFilesystem(args.url, args.api_key, writable=args.writable)

    print("Top level:", rspace.listdir("/"))
    print("\nWorkspace tree (plain names; IDs only where names collide):")
    print_tree(rspace, "/workspace", max_depth=4)

    # find the first file linked into any document field and download it
    for path, _dirs, files in rspace.walk("/workspace", namespaces=["details"]):
        if files:
            file_path = f"{path}/{files[0].name}"
            buffer = io.BytesIO()
            rspace.download(file_path, buffer)
            print(f"\nDownloaded {file_path}: {len(buffer.getvalue())} bytes")
            field_path = path
            break
    else:
        print("\nNo files linked into any document field.")
        return 0

    if args.writable:
        upload = io.BytesIO(b"sample,yield\nA,12.5\n")
        # upload(path, file): the last segment is the file to create, its parent the field
        rspace.upload(f"{field_path}/yields.csv", upload)  # Gallery upload + link into the field
        print(f"Uploaded yields.csv into {field_path}; the field now lists:")
        for name in rspace.listdir(field_path):
            print("   ", name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
