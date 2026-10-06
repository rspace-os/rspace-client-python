"""Run the spike against the bundled mock server: python tools/fsspec_spike/run_spike.py"""
import json, os, sys, urllib.request
sys.path.insert(0, os.path.dirname(__file__))
from rspace_client.tests.mock_rspace.server import run_in_thread
from fsspec_gallery import GalleryFileSystem, MountFileSystem

_, url = run_in_thread()
calls = lambda: json.load(urllib.request.urlopen(url + "/__mock/stats"))["requests"]
gfs = GalleryFileSystem(url, "key", writable=True, allow_delete=True)
root = MountFileSystem({"gallery": gfs})
n = calls(); print("ls /gallery:", root.ls("gallery", detail=False), "| calls:", calls() - n)
n = calls(); print("ls Images  :", [e["name"] for e in root.ls("gallery/Images")], "| calls:", calls() - n)
n = calls(); print("find       :", len(root.find("gallery")), "entries | calls:", calls() - n)
print("read       :", len(root.open("gallery/Documents/data.csv", "rb").read()), "bytes")
with root.open("gallery/Images/spike.txt", "wb") as f:
    f.write(b"hello fsspec")
print("wrote      :", gfs._last_upload["globalId"])
gfs._last_upload = None
with gfs.transaction:
    with gfs.open("Images/tx.txt", "wb") as f:
        f.write(b"deferred")
    print("in transaction, uploaded?", gfs._last_upload is not None)
print("after transaction, uploaded?", gfs._last_upload is not None)
