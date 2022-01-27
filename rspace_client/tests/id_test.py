#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Mon Oct  4 19:10:42 2021

@author: richard
"""
import unittest
from rspace_client.inv.inv import Id, ListContainer, Workbench


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
        id_a = Id({"id": 1234, "globalId": "SA1234"})
        self.assertEqual(1234, id_a.as_id())
        self.assertEqual("SA", id_a.prefix)

        self.assertRaises(TypeError, Id, {"x_not_an_id": 23})

    def test_id_from_container(self):
        minimal_container = {"id": 123, "globalId": "IC123", "cType": "LIST"}
        c = Id(ListContainer(minimal_container))
        self.assertEqual(123, c.as_id())

    def test_id_from_workbench(self):
        workbench = {"id": 123, "globalId": "BE123", "cType": "WORKBENCH"}
        c = Id(Workbench(workbench))
        self.assertEqual(123, c.as_id())
        self.assertEqual("BE", c.prefix)

    def test_repr(self):
        id_a = Id("SA1234")
        self.assertEqual("Id('SA1234')", repr(id_a))
        id_a = Id(1234)
        self.assertEqual("Id(1234)", repr(id_a))

    def test_str(self):
        id_a = Id("SA1234")
        self.assertEqual("SA1234", str(id_a))
        id_a = Id(1234)
        self.assertEqual("1234", str(id_a))

    def test_id_equals(self):
        self.assertEqual(Id(1234), Id(1234))
        self.assertEqual(Id("SA1234"), Id("SA1234"))

        self.assertNotEqual(Id(1234), Id(1235))
        self.assertNotEqual(Id(1234), Id("SA1234"))
        self.assertNotEqual(Id("IT1234"), Id("SA1234"))
        self.assertNotEqual(Id("SA1234"), Id(1234))
