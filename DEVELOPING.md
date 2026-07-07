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

 
### Making a release

- Get a clean test run 
- Update version in README.md and pyproject.toml
- update changelog to include the new version and required RSpace version
- tag with syntax like 'v2.2.0'    
- Build and submit to Pypi using `poetry publish`
