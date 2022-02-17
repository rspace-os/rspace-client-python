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
    GridContainerPost,
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
        print(f"Creating {shelves_per_freezer} shelves", file=sys.stderr)
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
        rc = []
        posts = []
        for i in range(0, n, 100):
            for j in range(i, min(n, i + 100) - i):
                c_post = GridContainerPost(
                    f"{name_prefix}-{i}", rows, columns, can_store_samples=store_samples
                )
                posts.append(c_post)

            results = self.cli.bulk_create_container(*posts)
            if not results.is_ok():
                raise Exception("creating didn't work")
            items = [c["record"]["globalId"] for c in results.success_results()]
            rc.extend(items)

        return rc

    def add_to_parent_tier(self, parents, parents_per_gp, items_per_parent, items):
        for j in range(len(parents)):
            k = items_per_parent
            rack_slice = items[j * k : (j * k) + k]
            br = ByRow(1, 1, 1, k, *rack_slice)
            self.cli.add_items_to_grid_container(parents[j], br)


#%%
### Configure the size of the freezer here ( or ask for input)
print(
    "Please enter the number of shelves, racks, trays and boxes to create. Boxes are 12 x 8"
)
shelves_per_freezer = int(input("Number of shelves? (1-5)"))
racks_per_shelf = int(input("Number of racks per shelf? (1-5)"))
trays_per_rack = int(input("Number of trays per rack? (1-5)"))
boxes_per_tray = int(input("Number of boxes per tray? (1-4)"))

params = (shelves_per_freezer, racks_per_shelf, trays_per_rack, boxes_per_tray)
for i in params:
    if i < 1 or i > 5:
        raise ValueError(f"Input arguments {params}out of range")
box_cols = 12
box_rows = 8
freezer_name = (
    f"-80:{shelves_per_freezer}x{racks_per_shelf}x{trays_per_rack}x{boxes_per_tray}"
)
user_freezer_name = input(f"Freezer name? ( default = {freezer_name})")
if len(user_freezer_name) > 0:
    freezer_name = user_freezer_name
print("Creating freezer", file=sys.stderr)
freezerFactory = FreezerCreator(
    cli, shelves_per_freezer, racks_per_shelf, trays_per_rack, boxes_per_tray
)
freezer = freezerFactory.create_freezer(freezer_name)


#%%
samples_created = 0
total_samples_to_create = len(freezer["boxes"]) * box_cols
print(f"Creating {total_samples_to_create} samples...", file=sys.stderr)
for box in freezer["boxes"]:
    st = time.perf_counter()
    print(f"Creating samples for  {box}", file=sys.stderr)
    posts = [SamplePost(f"s{i}", subsample_count=box_rows) for i in range(box_cols)]
    resp = cli.bulk_create_sample(*posts)
    col = 1
    samples_created = samples_created + box_cols
    print(
        f" created {box_cols} samples / {total_samples_to_create}", file=sys.stderr,
    )

    ## we can move 12 samples at a time
    ss_ids = []
    for result in resp.data["results"]:
        sample = result["record"]
        s_ids = [ss["globalId"] for ss in sample["subSamples"]]
        ss_ids.extend(s_ids)
    print(f"moving {box_cols} samples to {box}", file=sys.stderr)
    gp = ByColumn(col, 1, box_cols, box_rows, *ss_ids)
    cli.add_items_to_grid_container(box, gp)
    stop = time.perf_counter()
    print(f"Filling {box} took {(stop - st):.2f}s", file=sys.stderr)
print("COMPLETED", file=sys.stderr)
