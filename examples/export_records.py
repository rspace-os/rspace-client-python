#!/usr/bin/env python3

from __future__ import print_function
import rspace_client

# Parse command line parameters
# Parse command line parameters
client = rspace_client.utils.createClient()

# Export current user's records in XML format
print(
    "Export archive was downloaded to:",
    client.download_export("xml", "user", file_path="/tmp"),
)
