#!/usr/bin/env python3

from __future__ import print_function
import rspace_client

# Parse command line parameters
client = rspace_client.utils.createELNClient()
folder_id = client.create_folder("Word Import Folder")["id"]
print(
    "Importing an example word file in 'resources' folder : {}".format(
        "fish_method.doc"
    )
)
with open("resources/fish_method.doc", "rb") as f:
    rspaceDoc = client.import_word(f, folder_id)
    print(
        'File "{}" was imported to  folder {} as {} ({})'.format(
            f.name, folder_id, rspaceDoc["name"], rspaceDoc["globalId"]
        )
    )
