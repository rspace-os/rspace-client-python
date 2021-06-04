#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Thu Jun  3 09:50:47 2021

@author: richard
"""

from bs4 import BeautifulSoup
import json

class FieldContent:
    
    def __init__(self, html_content) :
        self.html = html_content
        self.soup = BeautifulSoup(self.html, 'html.parser')
        
    def get_datatables(self):
        divs = self.soup.find_all('div', class_ ='rsCalcTableDiv')
        table_data = divs[0]['data-tabledata'] 
        mydict = json.loads(table_data)
        return mydict['data']


with open('table.html') as f:
    text = f.read()
    field=FieldContent(text)
    print (field.get_datatables())

