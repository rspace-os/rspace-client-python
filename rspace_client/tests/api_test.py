#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Mon Jun  7 08:38:55 2021

@author: richard
"""


import rspace_client as cli
import unittest
import os
import pytest
import random
import string


RSPACE_URL_ENV = "RSPACE_URL"
RSPACE_APIKEY_ENV = "RSPACE_API_KEY"

def random_string(length):
    letters = string.ascii_lowercase
    return (''.join(random.choice(letters) for i in range(length)) )


class ApiClientIntegrationTest(unittest.TestCase):
    def setUp(self):
        if os.getenv(RSPACE_URL_ENV) is not None:
            self.rspace_url = os.getenv(RSPACE_URL_ENV)
        if os.getenv(RSPACE_APIKEY_ENV) is not None:
            self.rspace_apikey = os.getenv(RSPACE_APIKEY_ENV)
        print(f"{self.rspace_apikey} for {self.rspace_url}")
        if (
            self.rspace_url is None
            or self.rspace_apikey is None
            or len(self.rspace_url) == 0
            or len(self.rspace_apikey) == 0
        ):
            pytest.skip("Skipping API test as URL/Key are not defined")
        self.api = cli.ELNClient(self.rspace_url, self.rspace_apikey)

    def test_get_status(self):
        resp = self.api.get_status()
        self.assertEqual("OK", resp["message"])

    def test_get_documents(self):
        resp = self.api.get_documents()
        self.assertTrue(resp['totalHits'] > 0)
        self.assertTrue(len(resp['documents']) > 0)
        
    def test_get_documents_by_id(self):
        resp = self.api.get_documents()
        first_id = resp['documents'][0]['id']
        doc = self.api.get_document(first_id)
        self.assertEqual(first_id, doc['id'])
        
    def test_create_document(self):
        nameStr = random_string(10) 
        tag_str= random_string(5)
        resp = self.api.create_document(name=nameStr, tags=tag_str)
        print(resp)
        self.assertEqual(nameStr, resp['name'])
        self.assertEqual(tag_str, resp['tags'])