#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Mon Oct  4 19:10:42 2021

@author: richard
"""
import unittest
from rspace_client.inv.quantity_unit import QuantityUnit


class QuantityUnitTest(unittest.TestCase):
    def test_list_all(self):
        self.assertEqual(17, len(QuantityUnit.unit_labels()))

    def test_quantitty_exists(self):
        self.assertTrue(QuantityUnit.is_supported_unit("ml"))
        self.assertFalse(QuantityUnit.is_supported_unit("W"))

    def test_of(self):
        self.assertEqual(17, QuantityUnit.of("g/l")["id"])
        self.assertRaises(ValueError, QuantityUnit.of, "W")
