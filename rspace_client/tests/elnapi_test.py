#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Mon Jun  7 08:38:55 2021

@author: richard
"""
import pprint
import rspace_client.eln.eln as cli


from rspace_client.tests.base_test import BaseApiTest, random_string, get_datafile
from rspace_client.client_base import Pagination


class ELNClientAPIIntegrationTest(BaseApiTest):
    def setUp(self):
        self.assertClientCredentials()
        self.api = cli.ELNClient(self.rspace_url, self.rspace_apikey)

    def test_get_status(self):
        resp = self.api.get_status()
        self.assertEqual("OK", resp["message"])

    def test_get_documents(self):
        resp = self.api.get_documents()
        self.assertTrue(resp["totalHits"] > 0)
        self.assertTrue(len(resp["documents"]) > 0)

    def test_stream_documents(self):
        doc_gen = self.api.stream_documents(pagination=Pagination(page_size=1))
        d1 = next(doc_gen)
        d2 = next(doc_gen)
        self.assertNotEqual(d1["id"], d2["id"])

    def test_get_documents_by_id(self):
        resp = self.api.get_documents()
        first_id = resp["documents"][0]["id"]
        doc = self.api.get_document(first_id)
        self.assertEqual(first_id, doc["id"])

    def test_create_document(self):
        nameStr = random_string(10)
        tag_str = random_string(5)
        resp = self.api.create_document(name=nameStr, tags=tag_str)
        self.assertEqual(nameStr, resp["name"])
        self.assertEqual(tag_str, resp["tags"])

    def test_import_tree(self):
        tree_dir = get_datafile("tree")
        res = self.api.import_tree(tree_dir)
        self.assertEqual("OK", res["status"])
        ## f, 2sf, and 3files in each sf
        self.assertEqual(9, len(res["path2Id"].keys()))
        
    def test_import_tree_summary_doc_only(self):
        tree_dir = get_datafile("tree")
        res = self.api.import_tree(tree_dir, doc_creation = cli.DocumentCreationStrategy.SUMMARY_DOC)
        self.assertEqual("OK", res["status"])
        ## original folder + summary doc
        self.assertEqual(2, len(res["path2Id"].keys()))
        
    def test_import_tree_into_subfolder(self):
        folder = self.api.create_folder("tree-root")
        tree_dir = get_datafile("tree")
        res = self.api.import_tree(tree_dir, parent_folder_id=folder['id'])
        self.assertEqual("OK", res["status"])
        ## f, 2sf, and 3files in each sf
        self.assertEqual(9, len(res["path2Id"].keys()))
