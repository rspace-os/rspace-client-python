#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Mon Jun  7 08:38:55 2021

@author: richard
"""


import rspace_client.eln as cli
import rspace_client.tests.base_test as base_test
import unittest


class TestBasicFunction(unittest.TestCase):
    def setUp(self):
        dataDir = base_test.get_datafile("calculation_table.html")
        with open(dataDir) as f:
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

        EXPECTED_COL_COUNT = 4
        self.assertEqual(EXPECTED_COL_COUNT, len(array2d[0]))

    def test_filter_table(self):
        matching_tables = self.field.get_datatables(search_term="Nov")
        self.assertEqual(1, len(matching_tables))

        non_matching_tables = self.field.get_datatables(search_term="XXX")
        self.assertEqual(0, len(non_matching_tables))

    def test_include_empty_cols(self):
        tables = self.field.get_datatables(ignore_empty_columns=False)
        self.assertEqual(12, len(tables[0][0]))

    def test_include_empty_rows(self):
        tables = self.field.get_datatables(ignore_empty_rows=False)
        self.assertEqual(13, len(tables[0]))

    def test_get_text(self):
        htmlStr = "<div>Some text <p>in a para </p>after para</div>"
        field = cli.field_content.FieldContent(htmlStr)
        self.assertEqual("Some text in a para after para", field.get_text())
