#!/usr/bin/env python3

import argparse
import rspace_client

# Parse command line parameters
parser = argparse.ArgumentParser()
parser.add_argument("server", help="RSpace server URL (for example, https://community.researchspace.com)", type=str)
parser.add_argument("apiKey", help="RSpace API key can be found on 'My Profile'", type=str)
args = parser.parse_args()

client = rspace_client.Client(args.server, args.apiKey)

document_id = input('Document ID to search for (for example, 123)? ')

response = client.get_document(doc_id=document_id)
for field in response['fields']:
    for file in field['files']:
        download_metadata_link = client.get_link_contents(file, 'self')
        filename = '/tmp/' + download_metadata_link['name']
        print('Downloading to file', filename)
        client.download_link_to_file(download_metadata_link, 'enclosure', filename)