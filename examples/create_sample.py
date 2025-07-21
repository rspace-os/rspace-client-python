#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Mon Oct 18 20:23:16 2021

@author: richard
"""
import rspace_client
from rspace_client.inv.inv import Barcode, BarcodeFormat

inv_api = rspace_client.utils.createInventoryClient()

print("Creating a sample")

sample = inv_api.create_sample("My first sample")
print(
    f"Sample with id {sample['id']} was created with {len(sample['subSamples'])} subsamples"
)


barcodes = [
    Barcode(
        data="https://researchspace.com",
        format=BarcodeFormat.BARCODE,
        description="ResearchSpace"
    ),
    Barcode(
        data="https://www.wikipedia.org/",
        format=BarcodeFormat.BARCODE,
        description="Wikipedia"
    )
]

# Convert to dicts
barcode_dicts = [barcode.to_dict() for barcode in barcodes]
sample_with_barcode = inv_api.create_sample("sampleWithBarcodes", barcodes=barcodes)

print(
    f"Sample with id {sample_with_barcode['id']} was created with "
    f"{len(sample_with_barcode['subSamples'])} subsamples and "
    f"{len(sample_with_barcode.get('barcodes', []))} barcodes"
)