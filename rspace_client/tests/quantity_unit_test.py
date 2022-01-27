#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Mon Oct  4 19:10:42 2021

@author: richard
"""
import unittest
from rspace_client.inv.quantity_unit import QuantityUnit
from rspace_client.inv.inv import Quantity


class QuantityUnitTest(unittest.TestCase):
    def test_list_all(self):
        self.assertEqual(17, len(QuantityUnit.unit_labels()))

    def test_quantity_exists(self):
        self.assertTrue(QuantityUnit.is_supported_unit("ml"))
        self.assertFalse(QuantityUnit.is_supported_unit("W"))

    def test_of(self):
        self.assertEqual(17, QuantityUnit.of("g/l")["id"])
        self.assertRaises(ValueError, QuantityUnit.of, "W")

    def test_str(self):
        qu = QuantityUnit.of("ml")
        amount = Quantity(23, qu)
        self.assertEqual("23 ml", str(amount))

    def test_repr(self):
        qu = QuantityUnit.of("ml")
        amount = Quantity(23, qu)
        self.assertEqual("Quantity (23, 'ml')", repr(amount))

    def test_qu_eq(self):
        qu = QuantityUnit.of("ml")
        amount = Quantity(23, qu)
        amount2 = Quantity(23, qu)
        self.assertEqual(amount, amount2)

        amount3 = Quantity(23.0001, qu)
        amount4 = Quantity(23.0002, qu)
        self.assertEqual(amount3, amount4)
