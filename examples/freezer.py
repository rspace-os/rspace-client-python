#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Fri Jan 28 20:04:29 2022

@author: richardadams
"""

#%%
import sys, time
import rspace_client
cli = rspace_client.utils.createInventoryClient()
from rspace_client.inv.inv import (
    GridContainer,
    InventoryClient,
    ByRow,
    ByColumn,
    SamplePost,
)
#%%

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
        print("Creating freezer", file=sys.stderr)
        root = self.create_tier(1, name, self.shelves_per_freezer, 1)[0]

        ## shelves
        print("Creating shelves", file=sys.stderr)
        shelves = self.create_tier(
            self.shelves_per_freezer, "shelf", self.racks_per_shelf, 1
        )
        self.add_to_parent_tier([root], 1, self.shelves_per_freezer, shelves)

        ###  racks
        racks_total = racks_per_shelf * shelves_per_freezer
        print(f"Creating  {racks_total} racks", file=sys.stderr)
        racks = self.create_tier(racks_total, "rack", self.trays_per_rack, 1)
        self.add_to_parent_tier(
            shelves, self.shelves_per_freezer, self.racks_per_shelf, racks
        )

        ### Trays
        trays_total = racks_total * trays_per_rack
        print(f"Creating  {trays_total} trays", file=sys.stderr)
        trays = self.create_tier(trays_total, "tray", self.boxes_per_tray, 1)
        self.add_to_parent_tier(racks, self.racks_per_shelf, self.trays_per_rack, trays)

        ### Boxes
        boxes_total = trays_total * boxes_per_tray
        print(f"Creating  {boxes_total} boxes", file=sys.stderr)
        boxes = self.create_tier(boxes_total, "box", 8, 12, store_samples=True)
        self.add_to_parent_tier(trays, self.trays_per_rack, self.boxes_per_tray, boxes)

        return {
            "freezer": [root],
            "shelves": shelves,
            "racks": racks,
            "trays": trays,
            "boxes": boxes,
        }

    def create_tier(self, n, name_prefix, rows, columns, store_samples=False):
        items = []
        for i in range(n):
            item = self.cli.create_grid_container(
                f"{name_prefix}-{i}", rows, columns, can_store_samples=store_samples
            )
            items.append(item["globalId"])
        return items

    def add_to_parent_tier(self, parents, parents_per_gp, items_per_parent, items):
        for j in range(len(parents)):
            k = items_per_parent
            rack_slice = items[j * k : (j * k) + k]
            br = ByRow(1, 1, 1, k, *rack_slice)
            self.cli.add_items_to_grid_container(parents[j], br)


#%%
#cli = InventoryClient("http://pangolin8086.researchspace.com", "abcdefghijklmnop4")
shelves_per_freezer = 3
racks_per_shelf = 3
trays_per_rack = 3
boxes_per_tray = 3
print("Creating freezer", file=sys.stderr)
freezerFactory = FreezerCreator(
    cli, shelves_per_freezer, racks_per_shelf, trays_per_rack, boxes_per_tray
)
freezer = freezerFactory.create_freezer("-80- 3x3x3x3")


#%%

for box in freezer["boxes"]:
    st = time.perf_counter()
    print(f"Creating samples for  {box}", file=sys.stderr)
    posts = [SamplePost(f"s{i}", subsample_count=8) for i in range(12)]
    resp = cli.bulk_create_sample(*posts)
    col = 1
    
    ## we can move 8 samples at a time
    ss_ids = []
    for result in resp.data["results"]:
        sample = result["record"]
        s_ids = [ss["globalId"] for ss in sample["subSamples"]]
        ss_ids.extend(s_ids)
    print(f"moving 8 samples to {box}", file=sys.stderr)
    
    
    gp = ByColumn(col, 1, 12, 8, *ss_ids)
    cli.add_items_to_grid_container(box, gp)
    stop = time.perf_counter()
    print(f"Filling {box} took {(stop - st):.4f} ms", file=sys.stderr)
