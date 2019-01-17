#!/usr/bin/env python3

from __future__ import print_function
import argparse
import rspace_client

# Parse command line parameters
parser = argparse.ArgumentParser()
parser.add_argument("server", help="RSpace server URL (for example, https://community.researchspace.com)", type=str)
parser.add_argument("apiKey", help="RSpace API key can be found on 'My Profile'", type=str)
args = parser.parse_args()

client = rspace_client.Client(args.server, args.apiKey)

# Creating a new Basic document in Api Inbox folder
new_document = client.create_document(name='Python API Example Basic Document', tags=['Python', 'API', 'example'],
                       fields=[{'content': 'Some example text'}])
print('New document was successfully created with global ID {}'.format(new_document['globalId']))

# Uploading a file to the gallery
with open('resources/2017-05-10_1670091041_CNVts.csv', 'rb') as f:
    new_file = client.upload_file(f, caption='some caption')
    print('File "{}" was uploaded as {} ({})'.format(f.name, new_file['name'], new_file['globalId']))

# Editing the document to link to the uploaded file
updated_document = client.update_document(new_document['id'], fields=[{
    'content': 'Some example text. Link to the uploaded file: <fileId={}>'.format(new_file['id'])
}])
print('Document has been updated to link to the uploaded file.')

# Creating a document to show deletion
print("Creating a new document which will be deleted")
new_document2 = client.create_document(name='Python API Document for deletion', tags=['Python', 'API', 'example'],
                       fields=[{'content': 'Some example text'}])
deletedDoc = client.delete_document(new_document2['id'])
print('Document {} was deleted'.format(new_document2['id']))
print("You can see or restore the deleted document in web application in MyRSpace->Deleted Items")
