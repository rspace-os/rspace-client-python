#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Mon Oct  4 19:10:42 2021

@author: richard
"""
import unittest
from rspace_client.inv.inv import GridContainer
from rspace_client.tests import base_test
import json


class GridContainerTest(unittest.TestCase):
    def setUp(self):
        ## a grid container with 7 rows and 3 columns, cotaining 10 subsamples.
        path =  base_test.get_datafile("container_by_id.json")
        with open(path, 'r') as container:
            container_json = json.load(container)
            self.container = GridContainer(container_json)
            
    def test_grid_container(self):
      self.assertEqual(3, self.container.column_count())
      self.assertEqual(7, self.container.row_count())
      self.assertEqual(21, self.container.capacity())
      self.assertEqual(10, self.container.in_use())
      self.assertEqual(11, self.container.free())
      self.assertAlmostEqual(47.62, self.container.percent_full(), 2)
      
      
    def test_get_used_locations(self):
        used_locations = self.container.used_locations()
        self.assertTrue((2,1) in used_locations)
        self.assertTrue((2,7) in used_locations)
        self.assertFalse((1,4) in used_locations)
        
    def test_get_free_locations(self):
       free_locations = self.container.free_locations()
       used_locations = self.container.used_locations()
       
       s1 = set(free_locations)
       s2 = set(used_locations)
       self.assertEqual(0, len(s1.intersection(s2)))
       self.assertEqual(self.container.capacity(), len(free_locations) + len(used_locations))

    
