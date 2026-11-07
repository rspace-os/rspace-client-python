#!/usr/bin/env python3

import contextlib

import rspace_client

client = rspace_client.utils.createELNClient()

status_response = client.get_status()
print("RSpace API server status:", status_response["message"])
with contextlib.suppress(KeyError):
    # RSpace API version is returned only since 1.42
    print("RSpace API server version:", status_response["rspaceVersion"])
