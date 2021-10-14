#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Mon Oct  4 19:10:42 2021

@author: richard
"""
import unittest
import rspace_client.inv.inv as inv


def make_n_items_to_move(n: int, prefix="SS") -> list:
    return [f"{prefix}{i}" for i in range(n)]


class GridPlacementUnitTest(unittest.TestCase):
    def test_by_row(self):
        ss = make_n_items_to_move(10)
        by_row = inv.ByRow(1, 1, 2, 3, *ss)
        self.assertEqual(1, by_row.column_index)
        print(by_row.items_to_move)
        self.assertEqual(10, len(by_row.items_to_move))

    def test_by_column(self):
        ss = make_n_items_to_move(10)
        by_row = inv.ByColumn(1, 1, 2, 3, *ss)
        self.assertEqual(1, by_row.column_index)
        print(by_row.items_to_move)
        self.assertEqual(10, len(by_row.items_to_move))

    def test_all_gt_1_validation(self):
        ss = make_n_items_to_move(10)
        self.assertRaises(ValueError, inv.ByColumn, 0, 1, 2, 3, *ss)
        self.assertRaises(ValueError, inv.ByColumn, 1, 0, 2, 3, *ss)
        self.assertRaises(ValueError, inv.ByColumn, 1, 1, 0, 3, *ss)
        self.assertRaises(ValueError, inv.ByColumn, 1, 1, 2, 0, *ss)

    def test_indices_fit_in_grid(self):
        ss = make_n_items_to_move(10)
        self.assertRaises(ValueError, inv.ByColumn, 4, 1, 3, 3, *ss)
        self.assertRaises(ValueError, inv.ByColumn, 2, 3, 3, 2, *ss)

    def test_ByLocation(self):
        coords = [inv.GridLocation(i + 1, i + 2) for i in range(10)]
        ss = make_n_items_to_move(10)
        by_location = inv.ByLocation(coords, *ss)
        self.assertEqual(10, len(by_location.items_to_move))
        self.assertEqual(10, len(by_location.locations))
        self.assertEqual(inv.FillingStrategy.EXACT, by_location.filling_strategy)

    def test_validate_movable_type(self):
        ss = make_n_items_to_move(10, "SA")  # can't move samples, only subsamples
        self.assertRaises(ValueError, inv.ByColumn, 2, 3, 3, 2, *ss)
