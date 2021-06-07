#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Mon Jun  7 08:38:55 2021

@author: richard
"""


import rspace_client as cli
import unittest

class TestBasicFunction(unittest.TestCase):

    def setUp(self):
        with open('table.html') as f:
            text = f.read()
            field = cli.field_content.FieldContent(text)
            self.field = field

    def test_read_table(self):
        self.assertEqual(1, len(self.field.get_datatables()))
        
    def test_parse_table(self):
        array2d = self.field.get_datatables()[0]
        self.assertEqual(12, len(array2d))  
        ## all rows have same number of columns
        self.assertEqual(1, len(set((len(row) for row in array2d))))
        
        EXPECTED_COL_COUNT=  4
        self.assertEqual(EXPECTED_COL_COUNT, len(array2d[0]))
        
    def test_filter_table(self):
        matching_tables = self.field.get_datatables(search_term='Nov')
        self.assertEqual(1, len(matching_tables))
        
        non_matching_tables = self.field.get_datatables(search_term='XXX')
        self.assertEqual(0, len(non_matching_tables))
        
