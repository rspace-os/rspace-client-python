#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Imports samples, subsamples and containers into Inventory from CSV files.

The Inventory API supports importing samples, subsamples and (simple LIST)
containers from CSV. Instruments and Instrument Templates cannot be imported
from CSV.

The typical workflow is:
  1. Parse the CSV to discover its columns and the suggested field mappings /
     sample template (parse_csv_import_file).
  2. Adjust the mappings, then import (import_samples_csv / import_containers_csv
     / import_subsamples_csv, or import_csv_files for multi-file imports).

A field mapping maps a CSV column name to an RSpace field name, e.g. "name",
"description", "quantity", "expiry date", "identifier", "import identifier",
"parent container import id", "parent container global id",
"parent sample import id", "parent sample global id".
"""
import io

import rspace_client

inv_api = rspace_client.utils.createInventoryClient()


def csv_stream(content: str) -> io.BytesIO:
    stream = io.BytesIO(content.encode("utf-8"))
    stream.name = "import.csv"
    return stream


# 1. Parse a samples CSV to see what the server suggests
samples_csv = "Name,Supplier,Comment\nAntibody A,Acme,first\nAntibody B,Acme,second"
parse_result = inv_api.parse_csv_import_file(csv_stream(samples_csv), "SAMPLES")
print(f"Columns found: {parse_result['columnNames']}")
print(f"Suggested field mappings: {parse_result['fieldMappings']}")

# 2. Import the samples, creating a new Sample Template from the CSV columns
result = inv_api.import_samples_csv(
    csv_stream(samples_csv),
    field_mappings={"Name": "name", "Comment": "description"},
    template_info={"name": "Antibodies imported from CSV"},
)
print(f"Samples import status: {result['status']}")
print(f"  created {result['sampleResults']['successCount']} samples")

# Import containers (LIST containers only)
containers_csv = "Name\nFreezer shelf 1\nFreezer shelf 2"
container_result = inv_api.import_containers_csv(
    csv_stream(containers_csv), field_mappings={"Name": "name"}
)
print(f"Containers import status: {container_result['status']}")

# Import subsamples into a pre-existing sample, referencing it by Global Id
sample = inv_api.create_sample("Sample for CSV subsamples")
subsamples_csv = (
    "Name,Parent\n"
    f"Aliquot 1,{sample['globalId']}\n"
    f"Aliquot 2,{sample['globalId']}"
)
subsample_result = inv_api.import_subsamples_csv(
    csv_stream(subsamples_csv),
    field_mappings={"Name": "name", "Parent": "parent sample global id"},
)
print(f"Subsamples import status: {subsample_result['status']}")
