#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Thu Jun  3 09:50:47 2021

@author: richard
"""

from bs4 import BeautifulSoup
import re
class DataTable:
    
    def __init__(self, array_2d) :
        self.calculation_table = array_2d
    def row_count(self):
        return len(self.calculation_table)
    
        
class FieldContent:
    
    def __init__(self, html_content) :
        self.html = html_content
        self.soup = BeautifulSoup(self.html, 'html.parser')
        
    def get_datatables(self, search_term=None, ignore_empty_rows=True, ignore_empty_columns=True):
        divs = self.soup.find_all('div', class_ ='rsCalcTableDiv')
        all_tables= []
        for div in divs:
            if search_term is not None:
                if re.search(search_term, div.get_text(), re.IGNORECASE) is None:
                    continue
            trs = div.find_all('tr')
            all_r_data = []
        
            for tr in trs:
                r_data = [el.get_text().strip() for el in tr.find_all('td')]
                if (ignore_empty_rows is False or any([len(x) > 0 for x in r_data])):
                    all_r_data.append(r_data)
                       
            if ignore_empty_columns and len(all_r_data) > 0:
                colsToRemove=[]
                ## find empty columns
                for i in range(len(all_r_data[0])):
                    a_none= all(len(r[i]) == 0  for r in all_r_data)
                    if (a_none):
                        colsToRemove.append(i)
                ## remove each column
                for j in range(len(colsToRemove)):
                    for r in all_r_data:
                        r.pop(colsToRemove[j] - j)
                        
            all_tables.append(all_r_data)
        ## a list of 2d arrays. Each row has same number of columns
        return all_tables
    


with open('table.html') as f:
    text = f.read()
    field=FieldContent(text)
    print (field.get_datatables(search_term='nov',ignore_empty_columns=True))

