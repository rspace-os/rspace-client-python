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

# Uploading a file to the gallery
with open('resources/2017-05-10_1670091041_CNVts.csv', 'rb') as f:
    new_file = client.upload_file(f, caption='some caption')

# Editing the document to link to the uploaded file
client.update_document(new_document['id'], fields=[{
    'content': 'Some example text. Link to the uploaded file: <fileId={}>'.format(new_file['id'])
}])
