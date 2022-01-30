#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Fri Jan 28 20:04:29 2022

@author: richardadams
"""

#%%
from rspace_client.inv.inv import (
    GridContainer,
    InventoryClient,
    ByRow,
    ByColumn,
    SamplePost,
)


class FreezerCreator:
    def __init__(
        self,
        cli,
        shelves_per_freezer: int,
        racks_per_shelf: int,
        trays_per_rack: int,
        boxes_per_tray: int,
    ):
        self.shelves_per_freezer = shelves_per_freezer
        self.racks_per_shelf = racks_per_shelf
        self.trays_per_rack = trays_per_rack
        self.boxes_per_tray = boxes_per_tray
        self.cli = cli

    def create_freezer(self, name: str):
        root = self.create_tier(1, name, self.shelves_per_freezer, 1)[0]

        ## shelves
        shelves = self.create_tier(
            self.shelves_per_freezer, "shelf", self.racks_per_shelf, 1
        )
        self.add_to_parent_tier([root], 1, self.shelves_per_freezer, shelves)

        ###  racks
        racks_total = racks_per_shelf * shelves_per_freezer
        racks = self.create_tier(racks_total, "rack", self.trays_per_rack, 1)
        self.add_to_parent_tier(
            shelves, self.shelves_per_freezer, self.racks_per_shelf, racks
        )

        ### Trays
        trays_total = racks_total * trays_per_rack
        trays = self.create_tier(trays_total, "tray", self.boxes_per_tray, 1)
        self.add_to_parent_tier(racks, self.racks_per_shelf, self.trays_per_rack, trays)

        ### Boxes
        boxes_total = trays_total * boxes_per_tray
        boxes = self.create_tier(boxes_total, "box", 8, 12)
        self.add_to_parent_tier(trays, self.trays_per_rack, self.boxes_per_tray, boxes)

        return {
            "freezer": [root],
            "shelves": shelves,
            "racks": racks,
            "trays": trays,
            "boxes": boxes,
        }

    def create_tier(self, n, name_prefix, rows, columns):
        items = []
        for i in range(n):
            item = self.cli.create_grid_container(
                f"{name_prefix}-{i}", rows, columns, can_store_samples=False
            )
            items.append(item["globalId"])
        return items

    def add_to_parent_tier(self, parents, parents_per_gp, items_per_parent, items):
        print(
            f"adding {items} to {parents} where ppg = {parents_per_gp} and ipp={items_per_parent}"
        )
        for j in range(len(parents)):
            k = items_per_parent
            rack_slice = items[j * k : (j * k) + k]
            print(f"slice is {rack_slice}")
            br = ByRow(1, 1, 1, k, *rack_slice)
            print(f"adding {rack_slice} to parent {parents[j]}")
            self.cli.add_items_to_grid_container(parents[j], br)


#%%
cli = InventoryClient("http://localhost:8080", "abcdefghijklmnop4")
shelves_per_freezer = 2
racks_per_shelf = 2
trays_per_rack = 2
boxes_per_tray = 2
freezerFactory = FreezerCreator(
    cli, shelves_per_freezer, racks_per_shelf, trays_per_rack, boxes_per_tray
)
freezer = freezerFactory.create_freezer("-80aa")
print(freezer)


#%%
posts = [SamplePost(f"s{i}", subsample_count=8) for i in range(12)]
resp = cli.bulk_create_sample(*posts)
# print(resp)
