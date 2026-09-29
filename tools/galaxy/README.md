# Checking Galaxy's RSpace file source

Galaxy ships an `rspace` file source (`galaxy/files/sources/rspace.py`, since Galaxy 25.1)
built on this library's deprecated `rspace_client.eln.fs.GalleryFilesystem`, so changes here
can break Galaxy. `check_plugin.py` loads that real plugin through Galaxy's real
`ConfiguredFileSources`, without a Galaxy server:

```bash
python3 -m venv .galaxy-venv
.galaxy-venv/bin/pip install galaxy-files -e .

.galaxy-venv/bin/python tools/galaxy/check_plugin.py --mock /          # offline
.galaxy-venv/bin/python tools/galaxy/check_plugin.py / /GF8            # live RSpace via .env
```

Check that files have an integer `size` and a `ctime`, that `name` is the RSpace name while
`uri` uses the global ID, and that `source.list(path, query=...)` finds files by name. The
same four dependencies are pinned offline by `rspace_client/tests/galaxy_plugin_contract_test.py`.

A file source exposing `/inventory` and `/workspace` to Galaxy users belongs in Galaxy itself,
since Galaxy discovers file sources only inside its own package; see
`docs/unified-pyfilesystem-design.md`, section 8.
