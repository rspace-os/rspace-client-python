#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Fri Apr 15 16:11:08 2022

@author: richardadams
"""

import pytest, json, io

import rspace_client.tests.base_test as base
from rspace_client.inv import importer,inv


class CSVImportest(base.BaseApiTest):
    def setUp(self):
        """
        Skips tests if aPI client credentials are missing
        """
        self.assertClientCredentials()
        self.api = importer.Importer(self.rspace_url, self.rspace_apikey)
        

    def test_import_containers_from_file(self):
        col_map = importer.ContainerColumnMap("Name")
        mappings = (
            col_map.description_column("Alternative name")
            .id_column("Import Id")
            .parent_id_ref_column("Parent container")
            .build()
        )

        f = base.get_datafile("container_basic.csv")
        with open(f, "r") as container:
            resp = self.api.import_container_csv(container, mappings)
           
        self.assertTrue(resp.is_ok())
        self.assertEqual(5, resp.containers_imported())
        self.assertTrue(resp.is_in_default_container())
            
    def test_import_containers_into_existing_container(self):
        self.invapi = inv.InventoryClient(self.rspace_url, self.rspace_apikey)
        container_id = self.invapi.create_list_container("Import target")['globalId']
        col_map = importer.ContainerColumnMap("Name")
        mappings = (col_map.id_column("Import Id")
            .parent_rspace_id_column("RSParent")
            .build()
        )

        csv_string = io.StringIO(f"Name,Import Id,RSParent\nC1,1,{container_id}\nC2,2,{container_id}\n")
        
        resp = self.api.import_container_csv(csv_string, mappings)
        self.assertTrue(resp.is_ok())
        self.assertEqual(2, resp.containers_imported())
        self.assertFalse(resp.is_in_default_container())
        
    def test_import_nestedcontainers_into_existing_container(self):
        self.invapi = inv.InventoryClient(self.rspace_url, self.rspace_apikey)
        container_id = self.invapi.create_list_container("Nested Import target")['globalId']
        col_map = importer.ContainerColumnMap("Name")
        mappings = (col_map.id_column("Import Id")
            .parent_rspace_id_column("RSParent")
            .parent_id_ref_column("IdRef")
            .build()
        )

        fcsv_string = io.StringIO(f"Name,Import Id,RSParent,IdRef\nC1,1,{container_id},\nC2,2,,1\n")
        
        resp = self.api.import_container_csv(fcsv_string, mappings)
        self.assertTrue(resp.is_ok())
        self.assertEqual(2, resp.containers_imported())
        self.assertFalse(resp.is_in_default_container())
        
    def test_define_both_location_refs(self):
        self.invapi = inv.InventoryClient(self.rspace_url, self.rspace_apikey)
        container_id = self.invapi.create_list_container("Nested Import target")['globalId']
        col_map = importer.ContainerColumnMap("Name")
        mappings = (col_map.id_column("Import Id")
             .parent_rspace_id_column("RSParent")
             .parent_id_ref_column("IdRef")
             .build()
         )
        ## for row 2, we define 2 mutually incompatible locations foor the container.
        csv_string = io.StringIO(f"Name,Import Id,RSParent,IdRef\nC1,1,{container_id},\nC2,2,{container_id},1\n")
        resp = self.api.import_container_csv(csv_string, mappings)
        self.assertFalse(resp.is_ok())
        self.assertEqual(0, resp.containers_imported())
       

    def test_names_only(self):
        csv_string = io.StringIO("CName\nC1\nC2\n")
        colmap = importer.ContainerColumnMap("CName").build()
        resp = self.api.import_container_csv(csv_string, colmap)
        self.assertEqual(2, resp.containers_imported())

    def test_validate_columns_exist(self):
        csv_string = io.StringIO("CName\nC1\nC2\n")
        colmap = importer.ContainerColumnMap("XXXXX").build()
        self.assertRaises(ValueError, self.api.import_container_csv, csv_string, colmap)
        
    def test_stream_still_readable_after_validation(self):
        try:
            f = io.StringIO("CName\nC1\nC2\n")
            colmap = importer.ContainerColumnMap("XXX").build()
            self.api.import_container_csv(f, colmap)
            self.fail("Should throw exception")
        except:
            self.assertEqual("CName", f.readline().strip())
        
