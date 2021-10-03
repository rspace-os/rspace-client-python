#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Sun Oct  3 11:11:05 2021

@author: richard
"""


class QuantityUnit:
    data = [
        {"id": 1, "label": "items", "category": "dimensionless", "description": ""},
        {"id": 2, "label": "µl", "category": "volume", "description": ""},
        {"id": 3, "label": "ml", "category": "volume", "description": ""},
        {"id": 4, "label": "l", "category": "volume", "description": ""},
        {"id": 5, "label": "µg", "category": "mass", "description": ""},
        {"id": 6, "label": "mg", "category": "mass", "description": ""},
        {"id": 7, "label": "g", "category": "mass", "description": ""},
        {"id": 8, "label": "℃", "category": "temperature", "description": ""},
        {"id": 9, "label": "K", "category": "temperature", "description": ""},
        {"id": 10, "label": "F", "category": "temperature", "description": ""},
        {"id": 11, "label": "nmol/l", "category": "molarity", "description": ""},
        {"id": 12, "label": "μmol/l", "category": "molarity", "description": ""},
        {"id": 13, "label": "mmol/l", "category": "molarity", "description": ""},
        {"id": 14, "label": "mol/l", "category": "molarity", "description": ""},
        {"id": 15, "label": "µg/µl", "category": "concentration", "description": ""},
        {"id": 16, "label": "mg/ml", "category": "concentration", "description": ""},
        {"id": 17, "label": "g/l", "category": "concentration", "description": ""},
    ]

    @staticmethod
    def of(label):
        return [x for x in QuantityUnit.data if x["label"] == label][0]
