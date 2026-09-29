## Development

Python 3.9 or later is required. We aim to support only active versions of Python.

### Setup

Create a virtual environment with python 3.7 installed. If you use `conda`, you can do this

```
conda env create -f environment.yaml
conda activate rspace-client
``` 

We use `poetry` for dependency management. [Install Poetry] (https://python-poetry.org/docs/#installation)

From this directory, run 

`poetry install` 

to install all project dependencies into your virtual environment. 

### Running tests

Tests are a mixture of plain unit tests and integration tests that make calls to a live RSpace server.

#### Unit tests only

```
poetry run pytest -m "not integration"
```

#### Integration tests

Integration tests require credentials for a live RSpace instance. Create a `.env` file in the project root:

```
RSPACE_URL=https://<your-rspace-domain>
RSPACE_API_KEY=<your-api-key>
```

Then run:

```
poetry run pytest -m integration
```

Integration tests should be run with a new RSpace account that does not belong to any groups.

#### How CI runs integration tests

CI doesn't use a long-lived RSpace deployment or your credentials. Each run builds `rspace-web` from source and starts it fresh (Maven/Jetty, seeded database). That gives a known built-in `sysadmin1` account and API key (seeded by rspace-web's own dev/test fixtures), but authenticating purely via API key without ever logging in hits a lazy-initialization bug on that account's first write (its home folder isn't created yet). So CI does one plain HTTP login first (`.github/scripts/warmup_sysadmin.py`), which runs the same initialization correctly, then uses the account's API key directly for the whole suite. See `.github/workflows/codeql-and-tests.yml`.

If you want to reproduce this locally against your own from-source RSpace build (rather than any existing account), log in once as `sysadmin1` / `sysWisc23!` (e.g. run `warmup_sysadmin.py` against your instance) before pointing `RSPACE_API_KEY` at `abcdefghijklmnop12` in your `.env` - otherwise the first document-creation call will 500.
 
### Writing Tests
 
All top-level methods for use by client code should be unit-tested.

RSpace can be run on Docker on a developer machine, providing access to a sandbox environment.

#### Checking the Galaxy file source plugin

Galaxy ships an `rspace` file source built on this library's deprecated `rspace_client.eln.fs.GalleryFilesystem`, so changes here can break Galaxy. `rspace_client/tests/galaxy_plugin_contract_test.py` pins what it relies on and runs with the normal suite; a failure there is a release blocker. To drive Galaxy's real plugin through Galaxy's real `ConfiguredFileSources`, with no Galaxy server:

```
python3 -m venv .galaxy-venv && .galaxy-venv/bin/pip install galaxy-files -e .
.galaxy-venv/bin/python tools/galaxy/check_plugin.py --mock /
```

Drop `--mock` to run it against `RSPACE_URL` / `RSPACE_API_KEY`. Files must come back with an integer `size`; Galaxy's `RemoteFile` model rejects a null one.

A file source that exposes `/inventory` and `/workspace` to Galaxy users has to live in Galaxy itself, since Galaxy discovers file sources only inside its own package; what such a contribution has to carry is in [docs/unified-pyfilesystem-design.md](docs/unified-pyfilesystem-design.md), section 8.

#### Local mock server (no RSpace needed)

`rspace_client/tests/mock_rspace/` contains a dependency-free mock of the ELN and Inventory REST APIs (the endpoints the PyFilesystem implementations use) plus a harness that drives a filesystem the way Galaxy's `PyFilesystem2FilesSource` does and prints what Galaxy's file browser would show. The unit suite starts one for the whole session. See [rspace_client/tests/mock_rspace/README.md](rspace_client/tests/mock_rspace/README.md). Quick start:

```
poetry run python -m rspace_client.tests.mock_rspace.galaxy_harness --embedded --fs gallery ls /
```

 
### Making a release

- Get a clean test run 
- Update version in README.md and pyproject.toml
- update changelog to include the new version and required RSpace version
- tag with syntax like 'v2.2.0'    
- Build and submit to Pypi using `poetry publish`
