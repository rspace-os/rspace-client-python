#!/usr/bin/env python3

from __future__ import print_function
import argparse
import rspace_client
import sys
from datetime import date, timedelta

# Parse command line parameters
parser = argparse.ArgumentParser()
parser.add_argument("server", help="RSpace server URL (for example, https://community.researchspace.com)", type=str)
parser.add_argument("apiKey", help="RSpace API key can be found on 'My Profile'", type=str)
args = parser.parse_args()

client = rspace_client.Client(args.server, args.apiKey)

# Get documents created or modified last week
date_from = date.today() - timedelta(days=7)
response = client.get_activity(date_from=date_from)

print('All activities from {} to now:'.format(date_from.isoformat()))
for activity in response['activities']:
    print(activity)

# Get all activity for a document
print('Document ID to get all activity for (for example, SD123456)?')
document_id = sys.stdin.readline().strip()
response = client.get_activity(global_id=document_id)

print('Activities for document {}:'.format(document_id))
for activity in response['activities']:
    print(activity)
