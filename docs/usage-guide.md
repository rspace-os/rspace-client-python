# Usage Guide

This is the full worked-example reference for `rspace-client`. For install steps, a quick-start snippet, and a one-page feature overview, see the [README](../README.md).

All examples assume you've set `RSPACE_URL` and `RSPACE_API_KEY` as environment variables:

```bash
bash> export RSPACE_URL=https://myrspace.com
bash> export RSPACE_API_KEY=abcdefgh...
```

- [Using the library as a PyFilesystem implementation](#using-the-rspace_client-library-as-pyfilesystem-implementation)
- [A basic query to list documents](#a-basic-query-to-list-documents)
- [Iterating over pages of results](#iterating-over-pages-of-results)
- [Searching](#searching)
- [Retrieving document content](#retrieving-document-content)
- [Getting attached files](#getting-attached-files)
- [Creating / editing a document](#creating--editing-a-new-document)
- [Uploading a file to gallery](#uploading-a-file-to-gallery)
- [Linking to files and other RSpace documents](#linking-to-files-and-other-rspace-documents)
- [Activity](#activity)
- [Creating a Folder / Notebook](#creating-a-folder--notebook)
- [Getting Information About a Folder / Notebook](#getting-information-about-a-folder--notebook)
- [Forms](#forms)
- [Export](#export)

## Using the rspace_client library as PyFilesystem implementation

The library implements the [PyFilesystem](https://docs.pyfilesystem.org/en/latest/index.html)
API so that RSpace can be browsed like a drive, from your own code or from any tool that
speaks PyFilesystem (for example Galaxy's remote file sources). One `RSpaceFilesystem`
mounts everything under three fixed top-level folders:

```
/gallery      Gallery folders and files
/inventory    the bench(es) plus Containers, Samples, Templates; every record is a folder
/workspace    ELN folders, notebooks and documents; documents are folders of their fields
```

Entries are named after the records themselves, so a path reads like a path:
`/gallery/Documents/data.csv`. Where two records in the same folder share a name, the first
keeps the plain name and the rest carry their global ID, placed before the extension so the
file is still recognisable: `data.csv` and `data [GL112].csv`. A segment written as a global
ID always resolves, whatever style is in force, so `/gallery/GF11` and
`/gallery/Documents/data.csv [GL112]` work too. Pass `path_style="labelled"` for
`Name [GlobalID]` on every segment, or `path_style="id"` for bare IDs; both survive a rename,
which a plain name does not.

```python
from rspace_client.fs import RSpaceFilesystem, print_tree

rspace = RSpaceFilesystem(os.getenv("RSPACE_URL"), os.getenv("RSPACE_API_KEY"))

rspace.listdir("/")                      # ['gallery', 'inventory', 'workspace']
rspace.listdir("/gallery")               # ['Images', 'Documents', 'Chemistry', ...]
print_tree(rspace, "/workspace", max_depth=3)   # plain names, IDs only where names collide

with open("data.csv", "wb") as out:
    rspace.download("/gallery/Documents/data.csv", out)
```

With `RSPACE_API_KEY` set in the environment, `fs.open_fs("rspace://my.rspace.host")` returns
the same filesystem (add `?scheme=http` for a plain-http development server). The API key is
never part of the URL.

### Read-only by default

Filesystems are opened read-only. Pass `writable=True` to allow uploads and folder creation
and `allow_delete=True` to allow removals; a refused operation raises
`fs.errors.ResourceReadOnly`. `mounts=` narrows what is exposed, for a caller that only wants
part of RSpace: `RSpaceFilesystem(url, key, mounts=["workspace"])` shows only `/workspace`.
The names and the paths below them do not change, so narrowing the set later does not
invalidate paths into the branches that remain.

```python
rspace = RSpaceFilesystem(url, key, writable=True)

# upload(path, file) means what PyFilesystem says: path is the file to create, and its
# parent is the folder, record or field to put it in.

# Gallery: upload into a folder
with open("plate.png", "rb") as f:
    rspace.upload("/gallery/Images/plate.png", f)

# Inventory: attach a file to a record (container, sample, subsample, instrument)
with open("qc.pdf", "rb") as f:
    rspace.upload("/inventory/Containers/Freezer -80/Rack A/Plasmid pUC19 #1/qc.pdf", f)

# ELN: upload into a document field. The file goes to the Gallery and is linked into that field.
with open("yields.csv", "rb") as f:
    rspace.upload("/workspace/Project Alpha/Alpha protocol/Results/yields.csv", f)
```

### Gallery uploads and the media-type section rule

The RSpace Gallery is split into media-type sections (Images, Documents, Chemistry, ...) and
a file can only be placed in a folder whose section matches the file's media type. Uploading,
say, a PDF into a folder that lives in the Images section is rejected by the server.

By default a Gallery `upload` turns that rejection into a clear `GallerySectionMismatch` that
names the folder's section, rather than an opaque API error:

```python
from rspace_client.fs.gallery import GallerySectionMismatch

try:
    rspace.upload("/gallery/Images/notes.pdf", file_obj)
except GallerySectionMismatch as e:
    print(e)                 # explains the section clash
    print(e.folder_section)  # e.g. "Images"
```

Alternatively, opt in to automatic rerouting: on a mismatch the file is placed in the correct
section's inbox instead of failing. Set the policy once when constructing the Gallery
filesystem, or override it per call:

```python
from rspace_client.fs import GalleryFilesystem

gallery = GalleryFilesystem(url, key, writable=True, on_mismatch="reroute")
placement = gallery.upload("/Images/notes.pdf", file_obj)         # or per call: on_mismatch="reroute"

placement.rerouted        # True if it did not go in the requested folder
placement.section         # e.g. "Documents"
placement.path            # e.g. "Gallery/Documents/Api Inbox"
placement.file_global_id  # e.g. "GL999"
```

Rerouting places the file in the section's inbox, not in a subfolder matching the one you
requested. The unified `RSpaceFilesystem` takes the same option and passes it to its Gallery
branch, and any single upload can override it:

```python
rspace = RSpaceFilesystem(url, key, writable=True, on_mismatch="reroute")
placement = rspace.upload("/gallery/Images/notes.txt", notes_txt)  # lands in Documents

rspace = RSpaceFilesystem(url, key, writable=True)                # default: raise
placement = rspace.upload("/gallery/Images/notes.txt", notes_txt, on_mismatch="reroute")
```

### What the folders contain

- **Gallery**: folders (`GF`) and files (`GL`). Listings from the folder tree do not carry file
  sizes; `getinfo` on a file does. **The RSpace API cannot replace or delete a Gallery file**,
  so uploading to a path that already exists adds a second file rather than overwriting, and
  the original keeps the plain name while the new one carries its global ID. `remove` on a
  Gallery file is unsupported for the same reason. This is a server limitation, not a choice
  this library makes.
- **Inventory**: the root shows your bench(es) and the sections `Containers`, `Samples` and
  `Templates`. A container lists its child containers and subsamples as folders and its
  attachments as files; a sample lists its subsamples and attachments; instruments (`IN`)
  appear alongside them and carry attachments too. Because RSpace stores subsamples, not
  samples, in containers, every subsample folder also holds a shortcut `sample: <name>`
  listing that sample's attachments.
- **Inventory attachment fields**: a record carries files in two places, its own attachments,
  listed as files, and template-defined **attachment fields** (`SF`), listed as folders
  holding at most one file each. Only `attachment` fields appear, since no other field type
  can hold a file. Such a field accepts a file only while it is empty: RSpace replaces the
  current file rather than adding to it, which a folder does not suggest, so uploading into an
  occupied field raises `DestinationExists`. Remove the file first, then upload.

  Which records take a file is the server's decision, not this library's:

  | Record | Own attachments | Attachment fields |
  | --- | --- | --- |
  | Sample, subsample, container, instrument | yes | samples and instruments only, where the template defines one |
  | Sample template | no, the server refuses | the field is browsable |
  | Bench | no, the server refuses | none exist |

  A bench and a sample template look like any other record folder, but an upload to either is
  refused with `Unsupported` before anything is sent, because the server would refuse the link
  and the uploaded Gallery file could not be deleted afterwards.

  **An attachment you upload becomes a Gallery file**, exactly as the web interface's "link
  from Gallery" produces, so it is visible in `/gallery` and reusable elsewhere. The
  alternative the API also offers creates a file that exists only inside Inventory, invisible
  in the Gallery and findable only through the record it hangs off; pass `via_gallery=False`
  if you want that. `getinfo(...).raw["rspace"]["mediaFileGlobalId"]` names the Gallery file
  an attachment points at, and is `None` for an Inventory-only one.
- **Locked documents**: signing a document locks it. Its fields are listed with a `(signed)`
  suffix, so `/workspace/Project Alpha/Alpha protocol/Results (signed)` tells you before you
  try. Both spellings resolve, so a path stored before the document was signed keeps working.
  The suffix appears under the default `name` style only, since the other two spell a segment
  for a machine to parse. `getinfo(..., namespaces=["access"])` carries the same fact as
  permissions, on the document and on its fields, and `rspace.signed` is the raw flag.

  The document's own entry in its parent folder is **not** marked. The folder-tree endpoint
  that listing comes from does not report `signed`, so marking it would cost one extra request
  per document and break the one-call-per-listing property that makes large folders usable.
  Note also that `signed` is the only lock RSpace reports: a document shared read-only with
  you is equally unwritable and looks no different here.

- **Workspace**: the Home folder (the system folders Gallery and Templates are hidden).
  Folders and notebooks are folders; a document is a folder with one sub-folder per `text`
  field, the only ELN field type that holds files. Other types, including the legacy
  `attachment` type, are omitted and counted in the document's `rspace.hiddenFields`. Each
  field folder lists the files linked into it. `remove` on one of those unlinks it from the
  field and leaves the Gallery file in place. `makedir` creates Workspace folders only.

### Linking a file that is already in the Gallery

Copying within RSpace **links** rather than duplicates, which is what the web interface calls
"link from Gallery". No bytes move, and both places refer to the one file:

```python
rspace.copy("/gallery/Images/plate.png", "/inventory/Samples/Plasmid pUC19/plate.png")
rspace.copy("/gallery/Images/plate.png", "/workspace/Project Alpha/Alpha protocol/Results/plate.png")
```

Removing the link leaves the Gallery file alone. Without this a generic copy would download
the bytes and upload them again, leaving a second Gallery file that the RSpace API cannot
delete. A file already linked into a document field, or an Inventory attachment that came
from the Gallery, counts as a Gallery source too.

A link carries the Gallery file's own name, because that is all the API offers, so asking for
a different name at the destination falls through to a real copy that does move the bytes.
`overwrite=False`, the default, raises `DestinationExists` rather than adding a second link.

`upload(path, file)` follows PyFilesystem: the last segment names the file to create and its
parent is the container, so `writetext`, `writebytes`, `openbin` and `fs.copy` all behave
normally and a directory copied out will copy back in. The deprecated classes listed below
keep the older convention, where `path` named the container and the file took its name from
the file object.

A record or folder listing is a single API call; long listings stream in batches of
`page_size`, so a consumer that reads only the first few entries pays for only the first
batch. `getinfo(...).raw["rspace"]` holds the full RSpace record for any entry.

The individual filesystems are available on their own as `GalleryFilesystem`,
`InventoryFilesystem` and `WorkspaceFilesystem` in `rspace_client.fs`. The older import paths
`rspace_client.eln.fs.GalleryFilesystem` and `rspace_client.inv.attachment_fs` (also
`rspace_client.inv.fs`) still work, emit a `DeprecationWarning`, and keep their historical
behaviour (writable, bare-ID paths, attachment-only Inventory listings, and the
`GallerySectionMismatch` / `Placement` names re-exported).

## A basic query to list documents

First of all we'll get our URL and key from a command-line parameters.

```python
parser = argparse.ArgumentParser()
parser.add_argument("server", help="RSpace server URL (for example, https://community.researchspace.com)", type=str)
parser.add_argument("apiKey", help="RSpace API key can be found on 'My Profile'", type=str)
args = parser.parse_args()

client = rspace_client.ELNClient(args.server, args.apiKey)
documents = client.get_documents()
```

In the above example, the 'documents' variable is a dictionary that can easily be accessed for data:

```python
print(document['name'], document['id'], document['lastModified'])
```

To run the example scripts in the examples folder, cd to that folder, then run

```bash
python3 ExampleScript.py $RSPACE_URL $RSPACE_API_KEY
```

replacing ExampleScript.py with the name of the script you want to run.


### Iterating over pages of results

The JSON response also contains a `_links` field that uses HATEOAS conventions to provide links to related content. For document listings and searches, links to `previous`, `next`, `first` and `last` pages are provided when needed.

Using this approach we can iterate through pages of results, getting summary information for each document.

```python
while client.link_exists(response, 'next'):
    print('Retrieving next page...')
    response = client.get_link_contents(response, 'next')
```

A complete example of this is `examples/paging_through_results.py`.

## Searching

RSpace API provides  two sorts of search - a basic search that searches all searchable fields, and an advanced search where more fine-grained queries can be made and combined with boolean operators.

A simple search can be run by calling get_documents with a query parameter:

```python
  response = client.get_documents(query='query_text')

```

Here are some examples of advanced search constructs:

```python   
    // search by tag:
    search = json.dumps([terms:[[query:"ATag", queryType:"tag"]]])
    
    // by name
    search = json.dumps([terms:[[query:"AName", queryType:"name"]]])
    
    // for items created on a given date using IS0-8601 or yyyy-MM-dd format
    search = json.dumps([terms:[[query:"2016-07-23", queryType:"created"]]])
    
    // for items modified between 2  dates using IS0-8601 or yyyy-MM-dd format
    search = json.dumps([terms:[[query:"2016-07-23;2016-08-23 ", queryType:"lastModified"]]])
    
    // for items last modified on either of 2  dates:
    search = json.dumps([operator:"or",terms:[[query:"2015-07-06", queryType:"lastModified"],
                                    [query:"2015-07-07", queryType:"lastModified"] ])

    // search for documents created from a given form:
    search = json.dumps([terms:[[query:"Basic Document", queryType:"form"]]])
    
    // search for documents created from a given form and a specific tag:
    search = json.dumps([operator:"and", terms:[[query:"Basic Document", queryType:"form"], [query:"ATag", queryType:"tag"]]])        
```

or by using AdvancedQueryBuilder

```python
# Creation date (documents created between 2017-01-01 and 2017-12-01
advanced_query = rspace_client.AdvancedQueryBuilder().\
    add_term('2017-01-01;2017-12-01', rspace_client.AdvancedQueryBuilder.QueryType.CREATED).\
    get_advanced_query()
```

To submit these queries pass them as a parameter to `get_get_documents_advanced_query`:

```python
    response = client.get_documents_advanced_query(advanced_query)
    for document in response['documents']:
        print(document['name'], document['id'], document['lastModified'])

```

## Retrieving document content

Content can be retrieved from the endpoint `/documents/{id}` where {id} is a documentID.

Here is an example retrieving a document in CSV format taken from `forms.py` script:

```python
advanced_query = rspace_client.AdvancedQueryBuilder(operator='and').\
    add_term(form_id, rspace_client.AdvancedQueryBuilder.QueryType.FORM).\
    get_advanced_query()

response = client.get_documents_advanced_query(advanced_query)

print('Found answers:')
for document in response['documents']:
    print('Answer name:', document['name'])
    document_response = client.get_document_csv(document['id'])
    print(document_response)

```

## Getting attached files

Here's an example where we download file attachments associated with some documents. The code is in `download_attachments.py`.

```python
try:
    response = client.get_document(doc_id=document_id)
    for field in response['fields']:
        for file in field['files']:
            download_metadata_link = client.get_link_contents(file, 'self')
            filename = '/tmp/' + download_metadata_link['name']
            print('Downloading to file', filename)
            client.download_link_to_file(client.get_link(download_metadata_link, 'enclosure'), filename)
except ValueError:
    print('Document with id %s not found' % str(document_id))
```

## Creating / editing a new document

A document can be created by sending a POST request to `/documents`. Document name, form from which the document is created, tags and field values can be specified. The example code is in `create_document.py`.

```python
# Creating a new Basic document in Api Inbox folder
new_document = client.create_document(name='Python API Example Basic Document', tags=['Python', 'API', 'example'],
                                      fields=[{'content': 'Some example text'}])
```

You can also supply the `parentFolderId` of the workspace folder you want the document created in:


```python
# Creating a new Basic document in specified folder:
new_document = client.create_document(name='Python API Example Basic Document', tags=['Python', 'API', 'example'],
                                      fields=[{'content': 'Some example text'}], parent_folder_id=21);
```

It is possible to edit a document by sending a PUT request to `/documents/{id}`, where {id} is a documentID. Document name, tags and field values can be edited.

```python
# Editing the document to link to the uploaded file
client.update_document(document['id'], fields=[{'content': 'Edited example text.'}])
```

## Uploading a file to gallery

Any file that can be uploaded by using the UI can be uploaded by sending a POST request to `/files`. Also, it is possible to link to the file from any document as shown in `create_document.py` example.

```python
# Uploading a file to the gallery
with open('resources/2017-05-10_1670091041_CNVts.csv', 'rb') as f:
    new_file = client.upload_file(f, caption='some caption')
```


## Linking to files and other RSpace documents

There is a convenient syntax to link to either files or other RSpace documents.

To include links to files in your document content, you can use the syntax <fileId=12345> where '12345' is the ID of a file uploaded through the
`files/` endpoint.


```python
# Editing a document to link to an uploaded file
client.update_document(new_document['id'], fields=[{
    'content': 'Some example text. Link to the uploaded file: <fileId={}>'.format(new_file['id'])
}])
```

To include links to RSpace documents, folders or notebooks in your document content, you can use the syntax <docId=12345> where '12345' is the ID of an RSpace document,folder or notebook. E.g.


```python
# Editing a document to link to another RSpace document
client.update_document(new_document['id'], fields=[{
    'content': 'Some example text. Link to another document: <docId={}>'.format(anotherDocument['id'])
}])
```

## Activity

Access to the information that is available from the RSpace audit trail. This provides logged information on 'who did what, when'.

For example, to get all activity for a particular document:

```python
response = client.get_activity(global_id=document_id)

print('Activities for document {}:'.format(document_id))
for activity in response['activities']:
    print(activity)
```

To get all activity related to documents being created or modified last week:

```python
date_from = date.today() - timedelta(days=7)
response = client.get_activity(date_from=date_from, domains=['RECORD'], actions=['CREATE', 'WRITE'])

print('All activity related to documents being created or modified from {} to now:'.format(date_from.isoformat()))
for activity in response['activities']:
    print(activity)
```

## Creating a Folder / Notebook

A folder can be created by sending a POST request to `/folders`. All arguments are optional. Name, parent folder id and whether to create a notebook can be specified. For example, to create a folder named 'Testing Folder', `create_folder` method can be used:

```python
# Creating a folder named 'Testing Folder'
new_folder = client.create_folder('Testing Folder')
```

Notebooks can be created by setting `notebook=True`. To create a new notebook inside the previously created folder:

```python
# Creating a notebook named 'Testing Notebook' inside the previously created folder:
new_notebook = client.create_folder('Testing Notebook', parent_folder_id=new_folder['globalId'], notebook=True)
```

There are some restrictions on where you can create folders and notebooks, which are required to maintain consistent behaviour with the web application.

* You can't create folders or notebooks inside notebooks
* You can't create notebooks inside the Shared Folder; create them in a User folder first, then share. (Sharing is not yet supported in the API, but you can do this in the web application).

> **Note:** this is one of several places the Python client currently trails the full REST API — see [Compatibility & limitations](../README.md#compatibility--limitations) in the README for the general caveat.

## Getting Information About a Folder / Notebook

Folder or notebook information can be retrieved by sending a GET request to `/folders/{folderId}` where folder id is a numerical ID of a folder or a notebook. Python client accepts both numerical IDs and global IDs. Method `get_folder` can be used to get information about a folder:

```python
# Get information about a folder
folder_info = client.get_folder('FL123')  # or client.get_folder(123)
print(folder_info['globalId'], folder_info['name'])
```

## Forms

Published forms can be listed by sending a GET request to `/forms`. The results might be paginated if there are too many forms (see `create_form.py` example for a more in depth usage example).

```python
# Listing all published forms
response = client.get_forms()
for form in response['forms']:
    print(form['globalId'], form['name'])
```

A new form can be created by sending a POST request to `/forms`. Name, tags (optionally) and fields can be specified. Currently, supported types of form fields are: 'String', 'Text', 'Number', 'Radio', 'Date'. More information about the available parameters can be found in [API documentation](https://community.researchspace.com/public/apiDocs) or by looking at `create_form.py` source code.

```python
# Creating a new form
fields = [
    {
      "name": "A String Field",
      "type": "String",
      "defaultValue": "An optional default value"
    }
]
client.create_form('Test Form', tags=['testing', 'example'], fields=fields)
```

Form information can be retrieved by sending a GET request to `/forms/{formId}` where formId is a numerical ID of a form. Python client accepts both numerical IDs and global IDs.
```python
# Getting information about a form
response = client.get_form('FM3')  # or client.get_form(3)
print('Retrieved information about a form:', response['globalId'], response['name'])
print('Fields:')
for field in response['fields']:
    print(field['type'], field['name'])
```

A newly created form is not available to create documents from until it has been published. Sending a POST request to `/forms/{formId}/publish` publishes a form.
```python
# Publishing form FM123
client.publish_form('FM123')  # or client.publish_form(123)

# Unpublish the form
client.unpublish_form('FM123')  # or client.unpublish_form(123)
```

It is possible to share a form with your groups. Once it is shared the `accessControl.groupPermissionType` property is `READ`.
```python
# Sharing form FM123
client.share_form('FM123')

# Unsharing the form
client.unshare_form('FM123')
```

## Export

You can programmatically export your work in HTML or XML format. This might be useful if you want to make scheduled backups, for example. If you're an admin or PI you can export a particular user's work if you have permission.

You can also export specific documents, notebooks or folders. _Note_ this requires RSpace 1.69.19 or later.

Because export can be quite time-consuming, this is an asynchronous operation. On initial export you will receive a link to a job that you can query for progress updates. When the export has completed there will be a link to access the exported file - which may be very large.

This Python API client provides an easy to use method that handles starting an export, polling the job's status and downloading the exported archive once it's ready. For example, to export current user's work in XML format:

```python
export_archive_file_path = client.download_export('xml', 'user', file_path='/tmp')
```

or to export a group's work in HTML by id, passing an appendable file to record progress (requires >= 2.5):

```python
group_id=12345
export_archive_file_path = client.download_export('html', 'group', uid=group_id, file_path='/tmp', progress_log="a-writeable-file.log")
```

There are ```start_export(self, format, scope, id=None)``` and ```get_job_status(self, job_id)``` functions to start the export and check its status as well. When a job is complete, the response contains a download link that can be accessed directly, without making an API call:

```
{
 'id': 1595,
 'status': 'COMPLETED',
 'result': {'expiryDate': '2022-03-12T18:27:52.261Z',
  'size': 304694398,
  'checksum': '20038299',
  'algorithm': 'CRC32'},
 'percentComplete': 100.0,
 '_links': [{'link': 'https://community.researchspace.com/api/v1/export/RSpace-2022-06-11-18-28-html-123456.zip',
   'rel': 'enclosure'}]
}
```
