#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Fri Oct 29 16:55:19 2021

@author: richard
"""

import os
from rspace_client.eln import eln
import argparse

"""
Imports a directory of attachment files into RSpace, recreating the directory
structure in RSpace and creatingldocuments with links to the imported files, so
you can add context, metadata, additional information etc.

To run:
    
    python -m simple_tree_importer <RSPACE_URL> <KEY> <Directory to import>
    
"""


def main():
#   # maintain mapping of local directory paths to RSpace folder Ids
    path2Id={}
    folder = cli.create_folder(os.path.normpath(data_dir))
    path2Id[data_dir]=folder['id']
    
    for dirName, subdirList, fileList in os.walk(data_dir):
        for sf in subdirList:
            if sf not in path2Id.keys():
               rs_folder = cli.create_folder(os.path.basename(sf), path2Id[dirName])
               sf_path = os.path.join(dirName, sf)
               path2Id[sf_path] = rs_folder['id']
        for f in fileList:
            with open (os.path.join(dirName,f), "rb") as reader:
                rs_file = cli.upload_file(reader)
            doc_name = os.path.splitext(f)[0]
            ## just puts link to the document
            content_string = f"<fileId={rs_file['id']}>"
            parent_folder_id = path2Id[dirName]
            print (f"creating {f} as a document")
            rs_doc = cli.create_document(doc_name, 
                                    parent_folder_id=parent_folder_id,fields=[{'content':content_string}])
            

if __name__ == '__main__':
      parser = argparse.ArgumentParser()
      parser.add_argument(
          "server",
          help="RSpace server URL (for example, https://community.researchspace.com)",
          type=str,
      )
      parser.add_argument(
          "apiKey", help="RSpace API key can be found on 'My Profile'", type=str
      )
      
      parser.add_argument(
          "data_dir", help="The top level folder of your data export", type=str
      )
      args = parser.parse_args()
      url=args.server
      key=args.apiKey
      data_dir=args.data_dir
      cli = eln.ELNClient(url, key)
      print(cli.get_status())
      main()
        
