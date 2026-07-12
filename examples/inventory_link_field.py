#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Demonstrates Inventory "Link" extra-fields: typed, versioned links between
inventory items (and to ELN records).

Requires an RSpace server that supports Inventory Link fields
(server PR #803 / RSDEV-1131).
"""
import rspace_client
from rspace_client.inv.inv import ExtraField, RelationType
from rspace_client.inv.template_builder import TemplateBuilder

inv_api = rspace_client.utils.createInventoryClient()

# Two samples: one will link to the other.
target = inv_api.create_sample("Reference material")
source = inv_api.create_sample("Derived sample")

print(f"Created target {target['globalId']} and source {source['globalId']}")

# Add a Link extra-field to the source, pointing at the target with a
# relationship type from the DataCite/PIDINST vocabulary.
link_field = ExtraField.link(
    "Derived from",
    RelationType.IS_DERIVED_FROM,
    target["globalId"],
)
updated = inv_api.add_extra_fields(source["globalId"], link_field)
print(f"Source now has {len(updated['extraFields'])} extra field(s)")

# A raw string relationship type is also accepted, and a version pin can pin
# the link to a specific version of the target.
pinned = ExtraField.link("Cites", "Cites", target["globalId"], version_pin=1)

# Back-references: which items link to the target?
referencing = inv_api.get_referencing_items(target["globalId"])
print(f"Items referencing the target: {referencing}")

# A read-time summary of a link target (name, type, deleted/readable state).
summary = inv_api.get_link_target_summary(target["globalId"])
print(f"Target summary: {summary}")

# Sample templates can define Link fields, optionally whitelisting which
# relationship types are permitted for samples created from the template.
template_post = (
    TemplateBuilder("Linked-sample template", "ml")
    .link(
        "Related items",
        allowed_relation_types=[RelationType.IS_DERIVED_FROM, RelationType.CITES],
        mandatory=False,
    )
    .build()
)
template = inv_api.create_sample_template(template_post)
print(f"Created template {template['globalId']} with a Link field")
