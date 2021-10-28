#!/usr/bin/env python3

from __future__ import print_function

import rspace_client

client = rspace_client.utils.createELNClient()

status_response = client.get_status()
print("RSpace API server status:", status_response["message"])
try:
    print("RSpace API server version:", status_response["rspaceVersion"])
except KeyError:
    # RSpace API version is returned only since 1.42
    pass
