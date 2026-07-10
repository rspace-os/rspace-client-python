# rspace-client-python

[![PyPI version](https://img.shields.io/pypi/v/rspace-client.svg)](https://pypi.org/project/rspace-client/)
[![Python versions](https://img.shields.io/pypi/pyversions/rspace-client.svg)](https://pypi.org/project/rspace-client/)
[![License: Apache 2.0](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)

The official Python client for the [RSpace](https://www.researchspace.com) ELN and Inventory APIs. It wraps the raw REST endpoints in a Pythonic interface so you can create and search documents, manage Inventory samples and containers, export your work, and read/write Gallery and Inventory files — from a script, a Jupyter notebook, or your own application.

Don't have an RSpace account? Sign up for free at [community.researchspace.com](https://community.researchspace.com), or run [RSpace locally in Docker](https://github.com/rspace-os/rspace-docker). You'll need an API key from your [profile page](https://researchspace.helpdocs.io/article/v0dxtfvj7u-rspace-api-introduction) to use this client. This client is especially easy to use from Jupyter notebooks — see the [round-trip data analysis video](https://researchspace.helpdocs.io/article/5xqzm36v9t-video-round-trip-data-analysis-using-jupyter-notebook-and-the-rspace-api) for a walkthrough.

## Quick start

```bash
pip install rspace-client
```

```python
import os
from rspace_client.inv import inv
from rspace_client.eln import eln

inv_cli = inv.InventoryClient(os.getenv("RSPACE_URL"), os.getenv("RSPACE_API_KEY"))
eln_cli = eln.ELNClient(os.getenv("RSPACE_URL"), os.getenv("RSPACE_API_KEY"))

samples = inv_cli.list_samples()
print(f"There are {samples['totalHits']} samples")

print(eln_cli.get_status())
```

Set `RSPACE_URL` and `RSPACE_API_KEY` as environment variables first:

```bash
bash> export RSPACE_URL=https://myrspace.com
bash> export RSPACE_API_KEY=abcdefgh...
```

Full REST API reference is served by your own RSpace instance at `https://<YOUR_RSPACE_DOMAIN>/public/apiDocs` (e.g. `https://community.researchspace.com/public/apiDocs`).

## Core features

| Feature                                                          | What it does                                                                                                                                                                             |
| ---------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Documents & basic/advanced search                                | Create, read, and update documents; search by tag, name, form, or date; page through results                                                                                             |
| Inventory: samples, subsamples, containers                       | Create and manage samples, split/duplicate subsamples, organise items into containers                                                                                                    |
| Instruments & Instrument Templates *(new in 2.7.0, RSpace 2.24)* | Create, update, and manage Inventory instruments and instrument templates                                                                                                                |
| Export                                                           | Async export of a user's or group's work (or specific documents/notebooks/folders) to HTML or XML, with progress polling                                                                 |
| PyFilesystem access                                              | `GalleryFilesystem` and `InventoryAttachmentFilesystem` implement the [PyFilesystem](https://docs.pyfilesystem.org/en/latest/index.html) API for Gallery files and Inventory attachments |
| Notebook / Jupyter / R interop (`notebook_sync`)                 | Helpers for round-tripping data between RSpace notebook entries and Jupyter or R workflows                                                                                               |
| Activity / audit trail                                           | Query "who did what, when" for a record or across a date range                                                                                                                           |
| Forms                                                            | Create, publish, share, and list custom forms; create documents from them                                                                                                                |

Full worked examples for every feature above are in the **[Usage Guide](docs/usage-guide.md)**.

## Compatibility & limitations

|                      |                                     |
| -------------------- | ----------------------------------- |
| Python               | 3.9 or later (see `pyproject.toml`) |
| RSpace ELN API       | 1.69 or later                       |
| RSpace Inventory API | 1.73  or later                      |

**This client doesn't cover 100% of the REST API.** It's a convenience layer, and some capabilities are only exposed through the web application or the raw REST endpoints — for example, sharing a notebook into the Shared Folder currently has to be done in the UI (see [Creating a Folder / Notebook](docs/usage-guide.md#creating-a-folder--notebook)). If something you need isn't covered here, check the full REST API docs at `<YOUR_RSPACE_DOMAIN>/public/apiDocs` before assuming it isn't possible.

## Examples & notebooks

Runnable scripts in [`examples/`](examples) (run with `python3 examples/<script>.py $RSPACE_URL $RSPACE_API_KEY` from that folder):

| Script                          | What it demonstrates                                                                  |
| ------------------------------- | ------------------------------------------------------------------------------------- |
| `status.py`                     | Check RSpace server status and API version                                            |
| `create_document.py`            | Create a document, upload a file, and link the file into it                           |
| `create_folder_and_notebook.py` | Create, retrieve, and delete folders and notebooks                                    |
| `create_form.py`                | Create a custom form and list/page through published forms                            |
| `create_sample.py`              | Create an Inventory sample, including one with barcodes                               |
| `download_attachments.py`       | Download file attachments from a document                                             |
| `export_records.py`             | Export a selection of documents/notebooks/folders                                     |
| `freezer.py`                    | Build a freezer → shelf → rack → tray → box container hierarchy in Inventory          |
| `get_activity.py`               | Query the audit trail for a document, or for recent create/edit activity              |
| `import_directory.py`           | Import a local directory of files into RSpace                                         |
| `import_word_file.py`           | Import a Word (.docx) file as an RSpace document                                      |
| `paging_through_results.py`     | Page through document search results via HATEOAS links                                |
| `paging_through_users.py`       | Page through users and batch-process accounts (admin use case)                        |
| `search_documents_by_form.py`   | Find and export documents created from a specific form                                |
| `share_documents.py`            | Share a newly created document with a group                                           |
| `tree_upload.py`                | Bulk-import a converted eCAT export (folders of .docx/images) with resume/log support |

Interactive notebooks in [`jupyter_notebooks/`](jupyter_notebooks):

| Notebook                       | What it demonstrates                                                                                                                                                                                                 |
| ------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `rspace_demo.ipynb`            | Full round-trip workflow: pull data from RSpace, analyse it, write results back                                                                                                                                      |
| `rspace-demo-kaggle-v11.ipynb` | The same round-trip workflow using a Kaggle dataset — matches the [walkthrough video](https://researchspace.helpdocs.io/article/5xqzm36v9t-video-round-trip-data-analysis-using-jupyter-notebook-and-the-rspace-api) |
| `samples_to_lom.ipynb`         | Bulk-creates a notebook entry per sample assay, each with a List of Materials linking back to the sample's physical location                                                                                         |

(`proteins.csv` and `temp_data.csv` in the same folder are sample data used by these notebooks.)

## Community projects

See what others have built on top of RSpace and RSpace Python SDK  on the **[Community Projects](https://github.com/rspace-os/community/blob/main/community-projects/community-projects.md)** page. Built something with this client? Share it in an [office hour](https://github.com/rspace-os/community/blob/main/the%20rspace%20project/Guide/calendar.md) or open a PR to add it.

## Contributing

Contributions of all sizes are welcome — from a typo fix to a new feature. See [CONTRIBUTING.md](CONTRIBUTING.md) for how to get started, [DEVELOPING.md](DEVELOPING.md) for local setup and running tests, and the [Guide to the RSpace Project](https://github.com/rspace-os/community/blob/main/the%20rspace%20project/README.md) for the project's wider vision and governance.

## License & security

Apache 2.0 — see [LICENSE](LICENSE). Security policy is maintained org-wide at [rspace-os/.github](https://github.com/rspace-os/.github/blob/main/SECURITY.md).
