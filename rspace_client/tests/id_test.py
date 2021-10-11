#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Mon Oct  4 19:10:42 2021

@author: richard
"""
import unittest
from rspace_client.inv.inv import Id, GridContainer, ListContainer


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

    def test_id_from_dict(self):
        id_a = Id({'id':1234, 'globalId':'SA1234'})
        self.assertEqual(1234, id_a.as_id())
        self.assertEqual('SA', id_a.prefix)
        
        self.assertRaises(ValueError, Id, {'x_not_an_id':23})
        
    def test_id_from_container(self):
        minimal_container = {'id':123, 'globalId':'IC123', 'cType':'LIST'}
        c = Id(ListContainer(minimal_container))
        self.assertEqual(123, c.as_id())

        
