#!/usr/bin/env python3
"""
In order to use this example the account of your API key must belong to a group
so that you can share items
"""

from __future__ import print_function
import rspace_client


def printSharedItemNames(response):
    names = [l["shareItemName"] for l in response["shares"]]
    print(",".join(names))


# Parse command line parameters
client = rspace_client.utils.createELNClient()

groups = client.get_groups()
if len(groups) == 0:
    raise Exception("Cannot proceed as you are not a member of a group")

print(
    "Sharing into the first group found - '{}' ({}) - shareFolder = {}".format(
        groups[0]["name"], groups[0]["id"], groups[0]["sharedFolderId"]
    )
)

# Creating a new Basic document in Api Inbox folder
print("Creating a new document to share")
new_document = client.create_document(
    name="Python API Example2 Basic Document",
    tags=["Python", "API", "example"],
    fields=[{"content": "Some example text"}],
)
print(
    "New document was successfully created with global ID {}".format(
        new_document["globalId"]
    )
)

print("Creating subfolder in shared group folder...")
newFolder = client.create_folder("SharedSubfolder", groups[0]["sharedFolderId"])
newFolderId = newFolder["id"]

print(
    "Sharing document {} with group {} into folder {}".format(
        new_document["id"], groups[0]["name"], newFolderId
    )
)
shared = client.shareDocuments(
    [new_document["id"]], groups[0]["id"], sharedFolderId=newFolderId
)

print("The shared resource ID is {}".format(shared["shareInfos"][0]["id"]))
print(
    """You can see the shared item in RSpace webapp\
 in Shared->Lab Groups->{}_SHARED
 """.format(
        groups[0]["name"]
    )
)

print("Listing shared items")
sharedlist = client.get_shared_items()

printSharedItemNames(sharedlist)
while client.link_exists(sharedlist, "next"):
    print("Retrieving next page...")
    sharedlist = client.get_link_contents(shared, "next")
    printSharedItemNames(sharedlist)


# print ("Unsharing....")
# client.unshareItem(shared['shareInfos'][0]['id'])
# print("Unshared doc id {} from group {}".format(new_document['id'], groups[0]['name']))

print("Finished")
