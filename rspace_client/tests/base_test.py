#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Sat Oct  2 21:55:26 2021

@author: richard
"""
import unittest
import os

import string
import random
import pytest

RSPACE_URL_ENV = "RSPACE_URL"
RSPACE_APIKEY_ENV = "RSPACE_API_KEY"


def get_datafile(filename: str):
    return os.path.join(os.path.dirname(__file__), filename)


def get_any_datafile():
    return get_datafile("data/fish_method.doc")


def random_string(length=10):
    """
    Creates random lowercase string
    """
    letters = string.ascii_lowercase
    return "".join(random.choice(letters) for i in range(length))


class BaseApiTest(unittest.TestCase):
    def assertClientCredentials(self):
        if os.getenv(RSPACE_URL_ENV) is not None:
            self.rspace_url = os.getenv(RSPACE_URL_ENV)
        if os.getenv(RSPACE_APIKEY_ENV) is not None:
            self.rspace_apikey = os.getenv(RSPACE_APIKEY_ENV)

        if (
            self.rspace_url is None
            or self.rspace_apikey is None
            or len(self.rspace_url) == 0
            or len(self.rspace_apikey) == 0
        ):
            pytest.skip("Skipping API test as URL/Key are not defined")
