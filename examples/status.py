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

status_response = client.get_status()
print('RSpace API server status:', status_response['message'])
try:
    print('RSpace API server version:', status_response['rspaceVersion'])
except KeyError:
    # RSpace API version is returned only since 1.42
    pass
