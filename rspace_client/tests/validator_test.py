#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Mon Oct  4 19:10:42 2021

@author: richard
"""
import unittest
import datetime as dt
import rspace_client.validators as v


class ValidatorTest(unittest.TestCase):
    def test_validate_string(self):
        validator = v.String()
        validator.validate("hello")
        validator.validate("")
        validator.validate("")
        self.assertRaises(TypeError, validator.validate, 22)
        self.assertRaises(TypeError, validator.validate, dict())

    def test_validate_number(self):
        validator = v.Number()
        validator.validate(12)
        validator.validate(-3.4)
        validator.validate(3.2e10)
        self.assertRaises(TypeError, validator.validate, "Hello")
        self.assertRaises(TypeError, validator.validate, dict())

    def test_validate_all_of(self):
        validator = v.AllOf(["a", "b", "c"])
        validator.validate(["a"])
        validator.validate(["a", "c"])
        validator.validate(["a", "b", "c"])
        validator.validate([])  # no choice is fine

        self.assertRaises(TypeError, validator.validate, 2.3)
        self.assertRaises(TypeError, validator.validate, {})

    def test_validate_one_of(self):
        validator = v.OneOf(["a", "b", "c"])
        validator.validate("a")
        self.assertRaises(TypeError, validator.validate, 2.3)
        self.assertRaises(TypeError, validator.validate, ["a"])
        self.assertRaises(TypeError, validator.validate, [])
        self.assertRaises(TypeError, validator.validate, "x")

    def test_validate_date(self):
        validator = v.Date()
        dtime = dt.datetime(2011, 1, 22, 2, 30)
        validator.validate(dtime)
        validator.validate(dt.date(2011, 1, 22))

    def test_validate_time(self):
        validator = v.Time()
        dtime = dt.datetime(2011, 1, 22, 2, 30)
        validator.validate(dtime)
        validator.validate(dt.time(11, 30))
