## Development

Python 3.7 or later is required. We aim to support only active versions of Python.

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

Tests are a mixture of plain unit tests and integration tests making calls to an RSpace server.
To run all tests, set these environment variables,replacing with your own values

```
bash> export RSPACE_URL=https:/<your-rspace-domain>
bash> export RSPACE_API_KEY=abcdefgh...
```

If these aren't set, integration tests will be skipped.

Tests can be invoked:

```
poetry run pytest rspace_client/tests
```

They should be run with a new account that does not belong to any groups.
 
### Writing Tests
 
All top-level methods for use by client code should be unit-tested.

RSpace can be run on Docker on a developer machine, providing access to a sandbox environment.

 
    