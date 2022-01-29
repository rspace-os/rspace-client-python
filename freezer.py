#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Fri Jan 28 20:04:29 2022

@author: richardadams
"""

from  rspace_client.inv.inv import GridContainer, InventoryClient, ByRow,ByColumn


#%%
cli = InventoryClient("https://pangolin8086.researchspace.com", "abcdefghijklmnop9")
shelves_per_freezer = 2
racks_per_shelf = 2
trays_per_rack=2
boxes_per_tray=2
root = cli.create_grid_container("-80g", shelves_per_freezer, 1)
 
#%%
## shelves
shelves = []
for n in "ab":
    shelf = cli.create_grid_container(f"shelf-{n}", 1,racks_per_shelf)
    shelves.append(shelf['globalId'])

#%%
br = ByRow(1, 1, 1, shelves_per_freezer, *shelves)
cli.add_items_to_grid_container(root['id'], br)
    
#%%
###  racks
racks = []
racks_total = racks_per_shelf * shelves_per_freezer
for i in range(racks_total):
    rack = cli.create_grid_container(f"tray-rack-{i}", 1, trays_per_rack)
    racks.append(rack['globalId'])
    
#%%
for j in range (shelves_per_freezer):
    k = racks_per_shelf
    rack_slice = racks[j*k:(j*k)+k]
    br = ByColumn(1, 1, racks_per_shelf, 1, *rack_slice)
    cli.add_items_to_grid_container(shelves[j], br)
    
    
#%%
### Trays
trays = []
trays_total = racks_total * trays_per_rack
for i in range (trays_total):
    tray = cli.create_grid_container(f"tray-{i}", boxes_per_tray,1)
    trays.append(tray['globalId'])
    
#%%
for j in range (racks_total):
    k =trays_per_rack
    tray_slice = trays[j*k: (j*k)+k]
   # print(tray_slice)
    br = ByRow(1, 1, k, 1, *tray_slice)
   # print (f" moving {tray_slice} into {racks[j]}")
    cli.add_items_to_grid_container(racks[j], br)
    
#%%
### boxes
boxes = []
boxes_total=trays_total * boxes_per_tray
for i in range (boxes_total):
    box = cli.create_grid_container(f"box-{i}", 8,12)
    boxes.append(box['globalId'])
    
#%%
for j in range (trays_total):
    k=boxes_per_tray
    boxslice = boxes[j*k: (j*k)+k]
   # print(boxslice)
    br = ByRow(1, 1, 1, k, *boxslice)
   ## print (f" moving {boxslice} into {trays[j]}")
    cli.add_items_to_grid_container(trays[j], br)