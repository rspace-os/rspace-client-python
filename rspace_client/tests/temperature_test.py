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
        self.assertEqual("StorageTemperature (23, <TemperatureUnit.CELSIUS: 8>)", repr(temp))

    