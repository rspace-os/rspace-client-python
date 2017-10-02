# rspace-client-python

This project contains a client which helps calling RSpace APIs. There are some example Python scripts.

To begin with you'll need an account on an RSpace server and an API key which you can get from your profile page.

In these examples we'll be using the rspace_client package (code is in rspace_client folder) which provides an abstraction over lower-level libraries. It's compatible with both Python 2 and Python 3.

All the code listed here is in the project.

For full details of our API spec please see https://your.rspace.com/public/apiDocs

To install rspace-client and its dependencies, run
```bash
pip3 install rspace-client
```

To run the example scripts in the examples folder, cd to that folder, then run

```bash
python3 ExampleScript.py https://your.rspace.com MyAPIKey
```

replacing MyAPIKey with your key, and ExampleScript.py with the name of the script you want to run.

### A basic query to list documents

First of all we'll get our URL and key from a command-line parameters.

```python
parser = argparse.ArgumentParser()
parser.add_argument("server", help="RSpace server URL (for example, https://community.researchspace.com)", type=str)
parser.add_argument("apiKey", help="RSpace API key can be found on 'My Profile'", type=str)
args = parser.parse_args()

client = rspace_client.Client(args.server, args.apiKey)
documents = client.get_documents()
```

In the above example, the 'documents' variable is a dictionary that can easily be accessed for data:

```python
print(document['name'], document['id'], document['lastModified'])
```

#### Iterating over pages of results

The JSON response also contains a `_links` field that uses HATEOAS conventions to provide links to related content. For document listings and searches, links to `previous`, `next`, `first` and `last` pages are provided when needed.

Using this approach we can iterate through pages of results, getting summary information for each document.

```python
while client.link_exists(response, 'next'):
    print('Retrieving next page...')
    response = client.get_link_contents(response, 'next')
```

A complete example of this is `examples/paging_through_results.py`.

### Searching

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

### Retrieving document content

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

### Getting attached files

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

### Creating / editing a new document

A document can be created by sending a POST request to `/documents`. Document name, form from which the document is created, tags and field values can be specified. The example code is in `create_document.py`.

```python
# Creating a new Basic document in Api Inbox folder
new_document = client.create_document(name='Python API Example Basic Document', tags=['Python', 'API', 'example'],
                                      fields=[{'content': 'Some example text'}])
```

It is possible to edit a document by sending a PUT request to `/documents/{id}`, where {id} is a documentID. Document name, tags and field values can be edited.

```python
# Editing the document to link to the uploaded file
client.update_document(document['id'], fields=[{'content': 'Edited example text.'}])
```

### Uploading a file to gallery

Any file that can be uploaded by using the UI can be uploaded by sending a POST request to `/files`. Also, it is possible to link to the file from any document as shown in `create_document.py` example.

```python
# Uploading a file to the gallery
with open('resources/2017-05-10_1670091041_CNVts.csv', 'rb') as f:
    new_file = client.upload_file(f, caption='some caption')

# Editing the document to link to the uploaded file
client.update_document(new_document['id'], fields=[{
    'content': 'Some example text. Link to the uploaded file: <fileId={}>'.format(new_file['id'])
}])
```

### Activity

Access to the information that is available from the RSpace audit trail. This provides logged information on 'who did what, when’.

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

### Export

From RSpace 1.47 (API version 1.3) you can programmatically export your work in HTML or XML format. This might be useful if you want to make scheduled backups, for example. If you're an admin or PI you can export a particular user's work if you have permission.

Because export can be quite time-consuming, this is an asynchronous operation. On initial export you will receive a link to a job that you can query for progress updates. When the export has completed there will be a link to access the exported file - which may be very large.

This Python API client provides an easy to use method that handles starting an export, polling the job's status and downloading the exported archive once it's ready. For example, to export current user's work in XML format: 
```python
export_archive_file_path = client.download_export('xml', 'user', file_path='/tmp')
```

There are ```start_export(self, format, scope, id=None)``` and ```get_job_status(self, job_id)``` functions to start the export and check its status as well.
