"""Run inside the Galaxy container: both RSpace plugins (shipped PyFilesystem one and the fsspec
spike) through Galaxy's own ConfiguredFileSources, against the bundled mock RSpace server."""
import json, os, sys, tempfile, urllib.request, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, "/tmp/rspace_mock")  # docker cp rspace_client/tests/mock_rspace there
from mock_rspace.server import run_in_thread
from galaxy.files import ConfiguredFileSources, ConfiguredFileSourcesConf
from galaxy.files.models import FileSourcePluginsConfig
_, url = run_in_thread()
calls = lambda: json.load(urllib.request.urlopen(url + "/__mock/stats"))["requests"]
confs = {
    "shipped rspace (PyFilesystem2)": {"type": "rspace", "id": "old", "label": "old", "endpoint": url, "api_key": "k", "writable": True},
    "fsspec spike": {"type": "rspace_fsspec_spike", "id": "new", "label": "new", "endpoint": url, "api_key": "k", "writable": True, "fetch_sizes": True},
}
for title, conf in confs.items():
    print(f"\n== {title}")
    try:
        src = ConfiguredFileSources(FileSourcePluginsConfig(), ConfiguredFileSourcesConf(conf_dict=[conf])).get_file_source_path(f"gxfiles://{conf['id']}").file_source
    except Exception as exc:
        print("  plugin load ERROR:", type(exc).__name__, str(exc)[:200]); continue
    print("  class:", type(src).__name__, "| supports_pagination:", src.supports_pagination, "| supports_search:", getattr(src, "supports_search", None))
    try:
        root_entries, _ = src.list("/", limit=10)
        images = next(e.path for e in root_entries if e.name == "Images")
        documents = next(e.path for e in root_entries if e.name == "Documents")
    except Exception as exc:
        print("  root listing ERROR:", type(exc).__name__, str(exc)[:160]); continue
    for path in ("/", images):
        n = calls()
        try:
            entries, count = src.list(path, limit=10)
            print(f"  list {path}: {count} entries, {calls()-n} api calls")
            for e in entries:
                d = e.model_dump(); print(f"     {d.get('class_'):<9} {str(d.get('name')):<22} size={str(d.get('size','-')):<5} {d.get('uri')}")
        except Exception as exc:
            print(f"  list {path}: ERROR {type(exc).__name__}: {str(exc)[:160]}")
    try:
        entries, _ = src.list(images, query="gel", limit=10); print("  search 'gel':", [e.name for e in entries])
    except Exception as exc:
        print("  search: unsupported/ERROR", type(exc).__name__, str(exc)[:100])
    tmp = tempfile.mkdtemp(); native = os.path.join(tmp, "data.dat")
    try:
        entries, _ = src.list(documents, limit=20)
        first_file = next(e for e in entries if e.model_dump().get("class_") == "File")
        src.realize_to(first_file.path, native); print("  realize_to:", os.path.getsize(native), "bytes from", first_file.name)
        src.write_from(documents.rstrip("/") + "/from-galaxy.csv", native)
        entries, _ = src.list(documents, limit=20); print("  write_from -> listing now:", [e.name for e in entries])
    except Exception as exc:
        print("  transfer ERROR:", type(exc).__name__, str(exc)[:200])
