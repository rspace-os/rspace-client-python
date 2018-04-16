#!/usr/bin/env python3

from __future__ import print_function
import argparse
import rspace_client


def print_forms(response):
    for form in response['forms']:
        print(form['globalId'], form['name'])


# Parse command line parameters
parser = argparse.ArgumentParser()
parser.add_argument("server", help="RSpace server URL (for example, https://community.researchspace.com)", type=str)
parser.add_argument("apiKey", help="RSpace API key can be found on 'My Profile'", type=str)
args = parser.parse_args()

client = rspace_client.Client(args.server, args.apiKey)

print('Creating a folder:')
response = client.create_folder('Testing Folder')
print('Folder has been created:', response['globalId'], response['name'])

print('Creating a notebook in the folder:')
response = client.create_folder('Testing Notebook', parent_folder_id=response['globalId'], notebook=True)
print('Notebook has been created:', response['globalId'], response['name'])

print('Getting information about the parent folder:')
response = client.get_folder(response['parentFolderId'])
print(response['globalId'], response['name'])
