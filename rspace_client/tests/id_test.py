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
    

