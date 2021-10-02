#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Sat Oct  2 22:09:40 2021

@author: richard
"""
import rspace_client.tests.base_test as base
import rspace_client.inv.inv as cli

class InventoryApiTest(base.BaseApiTest):
    
    def setUp(self):
        self.assertClientCredentials()
        self.invapi = cli.InventoryClient(self.rspace_url, 
                                          self.rspace_apikey)
        
    def test_create_sample(self):
        sample_name = base.random_string(5)
        sample_tags = base.random_string(4)
        sample  = self.invapi.create_sample(name=sample_name, tags=sample_tags)
        self.assertEqual(sample_name, sample['name'])