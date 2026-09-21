# Mock RSpace server and Galaxy-like harness

An offline test environment for developing the RSpace PyFilesystem implementations
(see `docs/unified-pyfilesystem-design.md`). Standard library only, no extra
dependencies beyond what the client already needs.

Two pieces:

- **`server.py`** - a mock of the RSpace ELN (`/api/v1`) and Inventory
  (`/api/inventory/v1`) REST APIs covering the endpoints the filesystems use, backed by
  the in-memory dataset in `fixtures.py`. It counts requests so you can see what each
  filesystem operation costs.
- **`galaxy_harness.py`** - drives a filesystem exactly the way Galaxy's
  `PyFilesystem2FilesSource` does (`filterdir(..., namespaces=["details"])`, `walk`,
  `download`, `upload`) and prints the table Galaxy's remote-files browser would render,
  plus the number of API calls it took.

## Quick start

From the repository root, inside the poetry environment (`poetry shell` or prefix with
`poetry run`):

```bash
python -m rspace_client.tests.mock_rspace.galaxy_harness --embedded --fs gallery ls /
```

```bash
python -m rspace_client.tests.mock_rspace.galaxy_harness --embedded --fs gallery walk /
```

```bash
python -m rspace_client.tests.mock_rspace.galaxy_harness --embedded --fs inventory ls /IC200
```

`--embedded` starts the mock server in-process on a free port for a single command.
For an interactive session run the server separately and point the harness (or your own
Python) at it:

```bash
python -m rspace_client.tests.mock_rspace.server --port 8765 --verbose
```

```bash
python -m rspace_client.tests.mock_rspace.galaxy_harness --url http://127.0.0.1:8765 --fs gallery ls /GF11
```

Any non-empty `apiKey` header is accepted. In your own code:

```python
from rspace_client.fs import GalleryFilesystem
fs = GalleryFilesystem("http://127.0.0.1:8765", "mock-key")   # read-only; add writable=True to upload
print(fs.listdir("/"))
```

## Harness commands

| Command | What it does |
| --- | --- |
| `ls [path]` | Galaxy-style listing of one directory (`filterdir` with `details`). |
| `walk [path]` | Galaxy-style recursive listing (`walk`), depth limited by `--max-depth`. |
| `get <path> <out>` | `fs.download` a file to a local path. |
| `put <path> <local>` | `fs.upload` a local file to a destination file path (for example `/SS300/out.csv`). |
| `info <path>` | `getinfo` and dump the raw Info (shows the `rspace` namespace). |
| `stats` | Print the mock server's request counters. |

`--fs gallery` and `--fs inventory` use `rspace_client.fs.GalleryFilesystem` and
`rspace_client.fs.InventoryFilesystem`, which name entries after the records themselves by
default (`--path-style labelled` for `Name [GID]`, `id` for bare global IDs) and are
**read-only by default**: add `--writable`
for `put`/`makedir` and `--allow-delete` for removals. `--fs rspace` uses the unified
`RSpaceFilesystem` (`/gallery`, `/inventory` and `/workspace`).

### What the mock does not do

It answers the endpoints the filesystems call, with fixtures shaped like real responses, but
it is not a simulator. Most notably it does **not** enforce the Gallery's media-type section
rule, so an upload that a real server would reject (a PDF into an Images folder) succeeds
here. `GallerySectionMismatch` and the rerouting policy are covered by unit tests that mock
the API error instead. Check anything that depends on that rule against a real server.

The last line of each command, `RSpace API calls: N`, is the number of HTTP requests the
operation made. An earlier draft cost N+1 calls for `ls` on a folder with N children (one listing plus one
`getinfo` per child); the `rspace_client.fs` classes override `scandir` so a
plain listing is one call per directory. A `details` listing of a Gallery folder tops up the
file sizes the tree endpoint omits, one `GET /files/{id}` per file.

## What the fixture contains

```
ELN                                          Inventory
FL1  user1a (home)                           BE1   WB user1a (bench): IC203 Bench box (SS303), SS304
  GF2  Gallery (root)                        IC200 Freezer -80 [IF500 freezer_manual.pdf]
    GF10 Images: GL100 GL101, GF13/GL102       IC201 Rack A (grid): SS300 [IF502], SS301
    GF11 Documents: GL110 GL111 GL112          IC202 Rack B: SS302
    GF12 Chemistry (empty)                   IC204..IC215 Shelf 1..12 (one subsample each)
    GF14 Api Imports (default upload target) SA1000 Plasmid pUC19 [IF501] -> SS300 SS301
  FL3 Shared, FL4 Templates, FL5 Api Inbox, FL6 Imports   SA1001 E. coli DH5a -> SS302 SS303
  FL20 Project Alpha                         SA1002 Buffer stock -> SS304
    NB30 Lab notebook 2026: SD40 SD41        SA1003..SA1014 Sample 3..14
    SD42 Alpha protocol (typed fields)       IT1 Plasmid [IF503], IT2 Bacterial strain
  FL21 Project Beta: SD43
```

Deliberate features of the dataset:

- `GL111` and `GL112` are both named `data.csv` (name collisions).
- `SD42` has `text`, `attachment`, `number`, `date`, `string` and `choice` fields; only the
  text fields hold files. Field global IDs use the `FD` prefix, as on real servers.
- Home contains the system folders Gallery, Shared, Templates and Api Inbox.
- 13 top-level containers and 15 samples, so `/containers` and `/samples` paginate at the
  default page size. Use `?pageNumber=&pageSize=`; `_links` carry `next`/`prev`.
- Documents expose per-field `files`; `PUT /documents/{id}` re-derives them from
  `<fileId=N>` tokens in text fields, so upload-then-link round-trips.

## Endpoints implemented

ELN `/api/v1`: `GET /status`, `GET /folders/tree[/{id}]` (with `typesToInclude`),
`GET /folders/{id}`, `POST /folders`, `DELETE /folders/{id}`, `GET /files/{id}`,
`GET /files/{id}/file`, `POST /files` (multipart `file`, `folderId`, `caption`),
`GET /documents/{id}`, `PUT /documents/{id}`.

Inventory `/api/inventory/v1`: `GET /workbenches`, `GET /containers`,
`GET /containers/{id}?includeContent=` (422 for a bench, as on real servers),
`GET /workbenches/{id}?includeContent=`, `GET /samples`, `GET /samples/{id}`,
`GET /subSamples/{id}`, `GET /sampleTemplates`, `GET /sampleTemplates/{id}`,
`GET /instruments/{id}`, `GET /files/{id}`, `GET /files/{id}/file`, `POST /files` (multipart
`file` + JSON `fileSettings`), `POST /attachments` (link an existing Gallery file to a record),
`DELETE /files/{id}`.

Control: `GET /__mock/stats`, `POST /__mock/reset`.

## Using it from tests

```python
from rspace_client.tests.mock_rspace.server import run_in_thread
server, url = run_in_thread()          # free port, daemon thread
...
server.reset()                         # fresh fixture + zeroed counters
server.shutdown()
```

## Extending

Add records in `fixtures.py::_build` (builders keep parent/child links consistent), and
add a `(METHOD, regex, handler)` to `ELN_ROUTES` or `INV_ROUTES` in `server.py`. Keep the
JSON shapes aligned with the server DTOs in the sibling `rspace-web` checkout.
