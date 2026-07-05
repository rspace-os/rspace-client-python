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

In CI, the `integration-test` job boots RSpace the same way `rspace-web`'s `e2e.yml` does: it downloads
the latest release WAR, deploys it with `mvnw jetty:run-war -Denvironment=drop-recreate-db` against a
MariaDB service container, which loads RSpace's dev-test seed data. That seed data includes a `sysadmin1`
user with a fixed, known API key, so no key-generation step is needed.
 
### Writing Tests
 
All top-level methods for use by client code should be unit-tested.

RSpace can be run on Docker on a developer machine, providing access to a sandbox environment.

 
### Making a release

- Get a clean test run 
- Update version in README.md and pyproject.toml
- update changelog to include the new version and required RSpace version
- tag with syntax like 'v2.2.0'    
- Build and submit to Pypi using `poetry publish`
