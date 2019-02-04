#!/usr/bin/env python3

from __future__ import print_function
import rspace_client

# Parse command line parameters
client = rspace_client.utils.createClient()

# Creating a new Basic document in Api Inbox folder
new_document = client.create_document(name='Python API Example Basic Document', tags=['Python', 'API', 'example'],
                       fields=[{'content': 'Some example text'}])
print('New document was successfully created with global ID {}'.format(new_document['globalId']))

# Creating a document in a specific Workspace folder:
folder= client.create_folder("subfolder");
new_document2 = client.create_document(name='Basic Document in subfolder', parentFolderId=folder['id'],
                       fields=[{'content': 'Some example text'}])
print ("Created document id [{}] in folder id [{}]".format(new_document2['id'], folder['id']))


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
