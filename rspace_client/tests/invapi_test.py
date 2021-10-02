#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Sat Oct  2 22:09:40 2021

@author: richard
"""
import rspace_client.tests.base_test as base
import rspace_client.inv.inv as cli


class InventoryApiTest(base.BaseApiTest):
    def setUp(self):
        self.assertClientCredentials()
        self.invapi = cli.InventoryClient(self.rspace_url, self.rspace_apikey)

    def test_create_sample(self):
        sample_name = base.random_string(5)
        sample_tags = base.random_string(4)
        ef1 = cli.ExtraField("f1", cli.ExtraFieldType.TEXT, "hello")
        ef2 = cli.ExtraField("f2", cli.ExtraFieldType.NUMBER, 123)

        minTemp = cli.StorageTemperature(1, cli.TemperatureUnit.KELVIN)
        maxTemp = cli.StorageTemperature(4, cli.TemperatureUnit.KELVIN)

        sample = self.invapi.create_sample(
            name=sample_name,
            tags=sample_tags,
            extra_fields=[ef1, ef2],
            storage_temperature_min=minTemp,
            storage_temperature_max=maxTemp,
        )
        self.assertEqual(sample_name, sample["name"])
        self.assertEqual(2, len(sample["extraFields"]))
        self.assertEqual(4, sample["storageTempMax"]["numericValue"])

    def test_create_sample_name_only(self):
        sample = self.invapi.create_sample(base.random_string(5))
        self.assertIsNotNone(sample)
