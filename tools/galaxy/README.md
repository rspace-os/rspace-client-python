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

## The fsspec file source

`rspace_fsspec_source.py` is the reference Galaxy file source for `rspace_client.fs`
(`RSpaceFilesystem`, type `rspace_unified`), built on Galaxy's `FsspecFilesSource`. It is the
file proposed for Galaxy's own `galaxy/files/sources/rspace.py` once Galaxy drops the
PyFilesystem2 plugins (galaxyproject/galaxy#21832). Galaxy discovers file sources only inside
its own package, so to try it copy the file there, for example into a Galaxy container:

```bash
docker cp tools/galaxy/rspace_fsspec_source.py galaxy:/galaxy/lib/galaxy/files/sources/rspace_unified.py
```

and add a `type: rspace_unified` entry to `file_sources_conf.yml` (the module docstring shows
one). The container's `rspace-client` must contain `rspace_client.fs`. Galaxy 25.1 ships the
fsspec base class already; the plugin's hooks accept both the 25.1 and the 26.x signatures.
Verified 2026-10-06 against Galaxy 25.1 and RSpace 2.26: listing, search, pagination, import
and export through the web API and the upload picker.
