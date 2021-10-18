#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Mon Oct 18 20:23:16 2021

@author: richard
"""

import rspace_client

inv_api = rspace_client.utils.createInventoryClient()

print ("Creating a sample")

sample = inv_api.create_sample("My first sample")
print(f"Sample with id {sample['id']} was created with {len(sample['subSamples'])} subsamples")