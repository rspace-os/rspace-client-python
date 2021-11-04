#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Thu Nov  4 21:25:03 2021

@author: richard
"""
import enum
class DocumentCreationStrategy(enum.Enum):
    """
    Enum of choices of how to create summary documents containing links to uploaded
    directories of files. 
    """
    
    
    DOC_PER_FILE = 1
    """
     Create a summary doc for every file uploaded
    """
    SUMMARY_DOC = 2
    DOC_PER_SUBFOLDER = 3