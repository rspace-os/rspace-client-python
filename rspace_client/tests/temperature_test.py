#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Mon Oct  4 19:10:42 2021

@author: richard
"""
import unittest
from rspace_client.inv.inv import StorageTemperature, TemperatureUnit


class TemperatureUnitTest(unittest.TestCase):
    def test_temp_str(self):
        temp = StorageTemperature(23, TemperatureUnit.CELSIUS)
        self.assertEqual("23 TemperatureUnit.CELSIUS", str(temp))

    def test_temp_repr(self):
        temp = StorageTemperature(23, TemperatureUnit.CELSIUS)
        self.assertEqual(
            "StorageTemperature (23, <TemperatureUnit.CELSIUS: 8>)", repr(temp)
        )

    def test_temp_eq(self):
        temp = StorageTemperature(23, TemperatureUnit.CELSIUS)
        temp2 = StorageTemperature(23, TemperatureUnit.CELSIUS)
        self.assertEqual(temp, temp2)
        o = StorageTemperature(23, TemperatureUnit.KELVIN)
        self.assertNotEqual(temp, o)
        o = StorageTemperature(24, TemperatureUnit.CELSIUS)
        self.assertNotEqual(temp, o)
