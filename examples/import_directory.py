#!/usr/bin/env python3

import sys, pprint
import rspace_client
from rspace_client.eln import filetree_importer
from rspace_client.eln.dcs import DocumentCreationStrategy as DCS

# Parse command line parameters
# Parse command line parameters
client = rspace_client.utils.createELNClient()


# Import a directory of files
print(
    """
       This script recursively uploads a directory of files from your computer, then
       creates RSpace documents with links to the files. You can choose from one of three
       strategies as to how the documents are created.
       """
)
print("Please input an absolute path to a directory of files to upload")
path = sys.stdin.readline().strip()
filetree_importer.assert_is_readable_dir(path)

print("Please choose 1,2 or 3 for how summary documents should be made:")
print("One document per file: 1")
print("One summary document per subfolder: 2")
print("One summary document for all files: 3")

dcs = int(sys.stdin.readline().strip())

print("uploading files....")
result = client.import_tree(path, doc_creation=DCS(dcs))
print(
    "Results show success/failure and a mapping of the files to an RSpace folders and documents"
)
pprint.pp(result)
