#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Sat Oct  2 22:09:40 2021

@author: richard
"""
import rspace_client.tests.base_test as base
import rspace_client.inv.inv as cli
import rspace_client.inv.quantity_unit as qu

import datetime as dt


class InventoryApiTest(base.BaseApiTest):
    def setUp(self):
        """
        Skips tests if aPI client credentials are missing
        """
        self.assertClientCredentials()
        self.invapi = cli.InventoryClient(self.rspace_url, self.rspace_apikey)

    def test_create_sample(self):
        sample_name = base.random_string(5)
        sample_tags = base.random_string(4)
        ef1 = cli.ExtraField("f1", cli.ExtraFieldType.TEXT, "hello")
        ef2 = cli.ExtraField("f2", cli.ExtraFieldType.NUMBER, 123)

        minTemp = cli.StorageTemperature(1, cli.TemperatureUnit.KELVIN)
        maxTemp = cli.StorageTemperature(4, cli.TemperatureUnit.KELVIN)
        expiry_date = dt.date(2024, 12, 25)
        amount = cli.Quantity(5, qu.QuantityUnit.of('ml'))
        sample = self.invapi.create_sample(
            name=sample_name,
            tags=sample_tags,
            extra_fields=[ef1, ef2],
            storage_temperature_min=minTemp,
            storage_temperature_max=maxTemp,
            expiry_date=expiry_date,
            total_quantity=amount,
            subsample_count=12
            
        )
        self.assertEqual(sample_name, sample["name"])
        self.assertEqual(2, len(sample["extraFields"]))
        self.assertEqual(4, sample["storageTempMax"]["numericValue"])
        self.assertEqual(1, sample["storageTempMin"]["numericValue"])
        self.assertEqual(12, sample["subSamplesCount"])

        self.assertEqual(expiry_date.isoformat(), sample["expiryDate"])

    def test_create_sample_name_only(self):
        sample = self.invapi.create_sample(base.random_string(5))
        self.assertIsNotNone(sample)
