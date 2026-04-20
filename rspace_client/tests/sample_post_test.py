#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import unittest

from rspace_client.inv import inv


class SamplePostTest(unittest.TestCase):
    def test_sample_post_without_location_has_no_parent_fields(self):
        post = inv.SamplePost("sample")

        self.assertNotIn("parentContainers", post.data)
        self.assertNotIn("parentLocation", post.data)
        self.assertNotIn("removeFromParentContainerRequest", post.data)

    def test_sample_post_with_list_container_location(self):
        location = inv.ListContainerTargetLocation(123)
        post = inv.SamplePost("sample", location=location)

        self.assertEqual([{"id": 123}], post.data["parentContainers"])
        self.assertNotIn("parentLocation", post.data)

    def test_sample_post_with_grid_location(self):
        location = inv.GridContainerTargetLocation(123, 2, 3)
        post = inv.SamplePost("sample", location=location)

        self.assertEqual([{"id": 123}], post.data["parentContainers"])
        self.assertEqual({"coordX": 2, "coordY": 3}, post.data["parentLocation"])

    def test_sample_post_with_barcode_format_included_when_set(self):
        barcode = inv.Barcode(
            data="SA123",
            format=inv.BarcodeFormat.QR,
            description="test",
            newBarcodeRequest=True,
        )
        post = inv.SamplePost("sample", barcodes=[barcode])

        self.assertEqual(
            [
                {
                    "data": "SA123",
                    "format": "QR",
                    "description": "test",
                    "newBarcodeRequest": True,
                }
            ],
            post.data["barcodes"],
        )
