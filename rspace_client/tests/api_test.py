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


RSPACE_URL_ENV="RSPACE_URL"
RSPACE_APIKEY_ENV="RSPACE_API_KEY"
class TestBasicFunction(unittest.TestCase):

    def setUp(self):
        if os.getenv(RSPACE_URL_ENV) is not None:
            self.rspace_url=os.getenv(RSPACE_URL_ENV)
        if os.getenv(RSPACE_APIKEY_ENV) is not None:
            self.rspace_apikey=os.getenv(RSPACE_APIKEY_ENV)
        print (f"{self.rspace_apikey} for {self.rspace_url}")
        if self.rspace_url is None or self.rspace_apikey is None or len(self.rspace_url) == 0 or len(self.rspace_apikey) ==0:
           pytest.skip("Skipping API test as URL/Key are not defined") 
        
    

    def test_get_status(self):
        api = cli.ELNClient(self.rspace_url, self.rspace_apikey)
        resp = api.get_status()
        self.assertEqual("OK", resp['message'])
