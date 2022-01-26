#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Mon Oct  4 19:10:42 2021

@author: richard
"""
import unittest
from rspace_client.inv.inv import GridContainer, Container, GridLocation
from rspace_client.tests import base_test
import json


class GridContainerTest(unittest.TestCase):
    def setUp(self):
        ## a grid container with 7 rows and 3 columns, cotaining 10 subsamples.
        path = base_test.get_datafile("container_by_id.json")
        with open(path, "r") as container:
            container_json = json.load(container)
            self.container = GridContainer(container_json)
            
    def test_repr(self):
        self.assertEqual("GridContainer id='IC131085', storesContainers=True, storesSubsamples=True, percent_full=47.62",
                         str(self.container))

    def test_grid_container(self):
        self.assertEqual(3, self.container.column_count())
        self.assertEqual(7, self.container.row_count())
        self.assertEqual(21, self.container.capacity())
        self.assertEqual(10, self.container.in_use())
        self.assertEqual(11, self.container.free())
        self.assertAlmostEqual(47.62, self.container.percent_full(), 2)

    def test_get_used_locations(self):
        used_locations = self.container.used_locations()
        self.assertTrue((2, 1) in used_locations)
        self.assertTrue((2, 7) in used_locations)
        self.assertFalse((1, 4) in used_locations)

    def test_get_free_locations(self):
        free_locations = self.container.free_locations()
        used_locations = self.container.used_locations()

        s1 = set(free_locations)
        s2 = set(used_locations)
        self.assertEqual(0, len(s1.intersection(s2)))
        self.assertEqual(
            self.container.capacity(), len(free_locations) + len(used_locations)
        )

    def test_container_of(self):
        raw_json = self.container.data
        grid2 = Container.of(raw_json)
        self.assertTrue(grid2.is_grid())
        self.assertFalse(grid2.is_list())
        self.assertTrue(isinstance(grid2, GridContainer))

    def test_storable_content_types(self):
        raw_json = self.container.data
        raw_json["canStoreContainers"] = False
        grid = Container.of(raw_json)
        self.assertTrue(grid.accept_subsamples())
        self.assertFalse(grid.accept_containers())
    
    def test_grid_location_repr(self):
        cell = GridLocation(3,4)
        self.assertEqual("GridLocation(3, 4)", repr(cell))
        