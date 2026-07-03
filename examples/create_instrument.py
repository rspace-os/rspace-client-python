#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Creates an Instrument Template, and an Instrument based on it.
"""
import rspace_client
from rspace_client.inv import template_builder, sample_builder2

inv_api = rspace_client.utils.createInventoryClient()

print("Creating an Instrument Template")

it_json = (
    template_builder.InstrumentTemplateBuilder(
        "Microscope template", "A template for the lab's microscopes"
    )
    .string("Serial Number")
    .number("Calibration")
    .uri("Manual")
    .build()
)
instrument_template = inv_api.create_instrument_template(it_json)
print(
    f"Instrument Template with id {instrument_template['id']} was created with "
    f"{len(instrument_template['fields'])} fields"
)

print("Creating an Instrument with default field values")

instrument = inv_api.create_instrument(
    "My first microscope", instrument_template_id=instrument_template["id"]
)
print(f"Instrument with id {instrument['id']} was created")

print("Creating an Instrument from the template, with field values set")

ForInstrumentCreation = sample_builder2.FieldBuilderGenerator().generate_class(
    instrument_template
)
instrument_fields = ForInstrumentCreation()
instrument_fields.serial_number = "SN-1234"
instrument_fields.calibration = 4.7
instrument_fields.manual = "https://example.com/manual.pdf"

instrument_with_fields = inv_api.create_instrument(
    "My second microscope",
    instrument_template_id=instrument_template["id"],
    fields=instrument_fields.to_field_post(),
)
print(
    f"Instrument with id {instrument_with_fields['id']} was created with "
    f"{len(instrument_with_fields['fields'])} fields set"
)
