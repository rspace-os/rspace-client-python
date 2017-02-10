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