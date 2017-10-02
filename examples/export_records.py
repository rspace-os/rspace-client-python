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

# Export current user's records in XML format
print('Export archive was downloaded to:', client.download_export('xml', 'user', file_path='/tmp'))
