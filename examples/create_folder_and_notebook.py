#!/usr/bin/env python3

from __future__ import print_function
import rspace_client


def print_forms(response):
    for form in response['forms']:
        print(form['globalId'], form['name'])


# Parse command line parameters
client = rspace_client.utils.createClient()


print('Creating a folder:')
response = client.create_folder('Testing Folder')
print('Folder has been created:', response['globalId'], response['name'])

print('Creating a notebook in the folder:')
response = client.create_folder('Testing Notebook', parent_folder_id=response['globalId'], notebook=True)
print('Notebook has been created:', response['globalId'], response['name'])

print('Getting information about the parent folder:')
response = client.get_folder(response['parentFolderId'])
print(response['globalId'], response['name'])

print('Creating a folder to delete:')
response = client.create_folder('Testing Folder to delete')
folder_id=response['globalId']
print('Folder id [{}] with name "{}" has been created:'.format(folder_id , response['name']))
print("Deleting folder")
response=client.delete_folder( response['globalId'])
print("deleted folder {}".format(folder_id))

print("Listing all contents of home folder")
response=client.list_folder_tree()
print('Found {} items '.format(response['totalHits']))
for item in response['records']:
    print('{}, (id = {}), type = {}'.format(item['name'], item['id'], item['type']))

print ("Listing only documents and notebooks...")
response=client.list_folder_tree(None, ['document', 'notebook'])
print('Found {} items '.format(response['totalHits']))
for item in response['records']:
    print('{}, (id = {}), type = {}'.format(item['name'], item['id'], item['type']))