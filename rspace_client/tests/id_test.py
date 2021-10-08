#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Mon Oct  4 19:10:42 2021

@author: richard
"""
import unittest
from rspace_client.inv.inv import Id


class IdUnitTest(unittest.TestCase):
    def test_id(self):
        ida = Id(1234)
        self.assertEqual(1234, ida.as_id())
        id2 = Id("SA1235")
        self.assertEqual(1235, id2.as_id())
        self.assertEqual("SA", id2.prefix)
        id3 = Id("2234")
        self.assertEqual(2234, id3.as_id())

        self.assertRaises(ValueError, Id, "!!!!")
        
    def create_bulk(self):
        x = { "operationType": "MOVE", 
         "records": [ { "type": "SUBSAMPLE", "id": "851970",
                       "parentContainers": [ { "id": 720896} ],
                       "parentLocation": { "coordX": 1, "coordY": 1 } 
                       }]
        }
        
    def test_grid_ordering (self):
        row_count = 10
        col_count = 3
        grid = [ [0 for i in range(col_count)] for j in  range (row_count)]
        self.assertEqual(10, len(grid))
        self.assertEqual(3, len(grid[0]))
        
        items_to_add = [chr(65 + i) for i in range(17)]
        coords = [] #array of x,y coords
        ## fill by row
        counter = 0
        for i in items_to_add:
            x = counter % col_count + 1
            y = int(counter / col_count) + 1
            coords.append( { "type": "SUBSAMPLE", "id": i,
                       "parentContainers": [ { "id": 720896} ],
                       "parentLocation": { "coordX": x, "coordY": y } 
                       })
            counter = counter + 1
        print ("by  row")
        print(coords)
        coords = []
        counter = 0
        for i in items_to_add:
            x = int(counter / row_count) + 1
            y = counter % row_count + 1
            coords.append((x, y, i))
            counter = counter +1
        ## 
        print ("by  column")
        print(coords)
            