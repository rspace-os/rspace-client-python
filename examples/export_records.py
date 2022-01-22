#!/usr/bin/env python3

import sys
import rspace_client

# Parse command line parameters
# Parse command line parameters
client = rspace_client.utils.createELNClient()


# Export 1 or more  records in XML format
#print('Export archive was downloaded to:', client.download_export('xml', 'user', file_path='/tmp'))
print('Comma-separated list of Item IDs to export (for example, 123,456)?')
item_id = sys.stdin.readline().strip()
item_ids=item_id.split(',')

print('Include previous versions (y/n/)? (RSpace 1.69.51 or later)')
include_previous_versions = sys.stdin.readline().strip()
includePrev=False
if include_previous_versions.lower() == 'y':
    includePrev = True

download_file="selection"+item_ids[0]+".zip"
print("Exporting..checking progress in 30s")
client.download_export_selection(file_path=download_file,
  include_revision_history=includePrev,
   export_format="xml", item_ids=[item_id])
print("Done- downloaded to {}".format(download_file))
