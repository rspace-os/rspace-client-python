#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Mon Jun  7 08:38:55 2021

@author: richard
"""

import rspace_client.eln.eln as cli


from rspace_client.tests.base_test import BaseApiTest, random_string


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
