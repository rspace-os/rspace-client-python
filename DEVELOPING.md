## Development

Python 3.7 or later is required. We aim to support only active versions of Python.

### Setup

Create a virtual environment with python 3.7 installed. If you use `conda` you can do this

```
conda env create -f environment.yaml
conda activate rspace-client
``` 

We use `poetry` for dependency management

`poetry install` 
 
### Testing
 
All top-level methods for use by client code should be unit-tested; tests making API calls
can be skipped if no API/ URL is set in environment variables.

RSpace can be run on Docker on a developer machine, providing access to a sandbox environment.

 
    