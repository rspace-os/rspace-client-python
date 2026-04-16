#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Mon Jun  7 08:38:55 2021

@author: richard
"""
import os, os.path
import tempfile

import pytest

import rspace_client.eln.eln as cli
from rspace_client.eln.dcs import DocumentCreationStrategy


from rspace_client.tests.base_test import BaseApiTest, random_string, get_datafile
from rspace_client.client_base import Pagination


@pytest.mark.integration
class ELNClientAPIIntegrationTest(BaseApiTest):
    def setUp(self):
        self.assertClientCredentials()
        self.api = cli.ELNClient(self.rspace_url, self.rspace_apikey)

    def test_get_status(self):
        resp = self.api.get_status()
        self.assertEqual("OK", resp["message"])

    def test_upload_downloadfile(self):
        file = get_datafile("fish_method.doc")
        with tempfile.NamedTemporaryFile(suffix=".doc", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            with open(file, "rb") as to_upload:
                rs_file = self.api.upload_file(to_upload)
                self.api.download_file(rs_file["id"], tmp_path)
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    def test_get_documents(self):
        self.api.create_document(name=random_string(10))
        resp = self.api.get_documents()
        self.assertTrue(resp["totalHits"] > 0)
        self.assertTrue(len(resp["documents"]) > 0)

    def test_stream_documents(self):
        self.api.create_document(name=random_string(10))
        self.api.create_document(name=random_string(10))
        doc_gen = self.api.stream_documents(pagination=Pagination(page_size=1))
        d1 = next(doc_gen)
        d2 = next(doc_gen)
        self.assertNotEqual(d1["id"], d2["id"])

    def test_get_documents_by_id(self):
        created = self.api.create_document(name=random_string(10))
        doc = self.api.get_document(created["id"])
        self.assertEqual(created["id"], doc["id"])

    def test_create_document(self):
        nameStr = random_string(10)
        tag_str = random_string(5)
        resp = self.api.create_document(name=nameStr, tags=tag_str)
        self.assertEqual(nameStr, resp["name"])
        self.assertEqual(tag_str, resp["tags"])

    def test_import_tree(self):
        tree_dir = get_datafile("tree")
        folder = self.api.create_folder("tree-" + random_string(6))
        res = self.api.import_tree(tree_dir, parent_folder_id=folder["id"])
        self.assertEqual("OK", res["status"])
        ## f, 2sf, and 3files in each sf
        self.assertEqual(9, len(res["path2Id"].keys()))

    def test_import_tree_include_dot_files(self):
        tree_dir = get_datafile("tree")
        folder = self.api.create_folder("tree-" + random_string(6))
        res = self.api.import_tree(tree_dir, parent_folder_id=folder["id"], ignore_hidden_folders=False)
        self.assertEqual("OK", res["status"])
        ## f, 2sf, and 3files in each sf + hidden
        self.assertTrue(len(res["path2Id"].keys()) >= 9)

    def test_import_tree_summary_doc_only(self):
        tree_dir = get_datafile("tree")
        folder = self.api.create_folder("tree-" + random_string(6))
        res = self.api.import_tree(
            tree_dir, parent_folder_id=folder["id"], doc_creation=DocumentCreationStrategy.SUMMARY_DOC
        )
        self.assertEqual("OK", res["status"])
        ## original folder + summary doc
        self.assertEqual(2, len(res["path2Id"].keys()))

    def test_import_tree_summary_doc_per_subfolder(self):
        tree_dir = get_datafile("tree")
        folder = self.api.create_folder("tree-" + random_string(6))
        res = self.api.import_tree(
            tree_dir, parent_folder_id=folder["id"], doc_creation=DocumentCreationStrategy.DOC_PER_SUBFOLDER
        )
        self.assertEqual("OK", res["status"])
        ## original folder + 2 sf + 2 summary docs
        self.assertEqual(5, len(res["path2Id"].keys()))

    def test_import_tree_into_subfolder(self):
        folder = self.api.create_folder("tree-root-" + random_string(6))
        tree_dir = get_datafile("tree")
        res = self.api.import_tree(tree_dir, parent_folder_id=folder["id"])
        self.assertEqual("OK", res["status"])
        ## f, 2sf, and 3files in each sf
        self.assertEqual(9, len(res["path2Id"].keys()))
        
    def test_export_all_work_with_log_file(self):
        with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as f:
            file_path = f.name
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            log_file = f.name
        try:
            self.api.export_and_download("html", "user", file_path, progress_log=log_file, wait_between_requests=5)
            self.assertTrue(os.path.getsize(log_file) > 0)
            self.assertTrue(os.path.getsize(file_path) > 0)
        except Exception as e:
            self.fail("Unexpected exception" + str(e))
        finally:
            for p in (file_path, log_file):
                if os.path.exists(p):
                    os.remove(p)

    def test_export_all_work_with_no_file(self):
        with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as f:
            file_path = f.name
        try:
            self.api.export_and_download("html", "user", file_path, wait_between_requests=5)
            self.assertTrue(os.path.getsize(file_path) > 0)
        except Exception as e:
            self.fail("Unexpected exception" + str(e))
        finally:
            if os.path.exists(file_path):
                os.remove(file_path)
            
            
