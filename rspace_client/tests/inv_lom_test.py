#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Tue Oct 19 21:41:03 2021

@author: richard
"""
import rspace_client.tests.base_test as base
from rspace_client.inv import inv
from rspace_client.eln import eln


class LomApiTest(base.BaseApiTest):
    def setUp(self):
        """
        Skips tests if aPI client credentials are missing
        """
        self.assertClientCredentials()
        self.invapi = inv.InventoryClient(self.rspace_url, self.rspace_apikey)
        self.elnapi = eln.ELNClient(self.rspace_url, self.rspace_apikey)

    def test_create_lom(self):
        doc = self.elnapi.create_document("with_lom")
        field_id = doc["fields"][0]["id"]
        item_to_add = self.invapi.create_sample("s1")
        lom = self.invapi.create_list_of_materials(
            field_id, "lom1", "description", item_to_add, item_to_add["subSamples"][0]
        )
        self.assertEqual("lom1", lom["name"])
        self.assertEqual("description", lom["description"])
        self.assertEqual(2, len(lom["materials"]))
        created_id = lom["id"]
        lom_for_doc = self.invapi.get_list_of_materials_for_document(doc["globalId"])
        self.assertEqual(created_id, lom_for_doc[0]["id"])

        lom_for_field = self.invapi.get_list_of_materials_for_field(field_id)
        self.assertEqual(created_id, lom_for_field[0]["id"])
