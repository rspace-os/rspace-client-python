#!/usr/bin/env python3

from __future__ import print_function
import rspace_client
import sys
from datetime import date, timedelta

# Parse command line parameters
# Parse command line parameters
client = rspace_client.utils.createELNClient()

# Get all activity related to documents being created or modified last week
date_from = date.today() - timedelta(days=7)
response = client.get_activity(
    date_from=date_from, domains=["RECORD"], actions=["CREATE", "WRITE"]
)

print(
    "All activity related to documents being created or modified from {} to now:".format(
        date_from.isoformat()
    )
)
for activity in response["activities"]:
    print(activity)

# Get all activity for a document
print("Document ID to get all activity for (for example, SD123456)?")
document_id = sys.stdin.readline().strip()
response = client.get_activity(global_id=document_id)

print("Activities for document {}:".format(document_id))
for activity in response["activities"]:
    print(activity)
