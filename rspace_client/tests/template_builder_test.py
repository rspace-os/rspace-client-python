#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Mon Jun  7 08:38:55 2021

@author: richard
"""


from rspace_client.inv.template_builder import TemplateBuilder
import unittest

builder = None
class TemplateBuilderTest(unittest.TestCase):

    
    
          


    def test_add_radio(self):
        builder = TemplateBuilder("myTemplate")      
        builder.radio("r1", ['a', 'b', 'c'], 'a')
        self.assertEqual(1, builder.field_count())
        self.assertEqual(['a'], builder._fields()[0]['selectedOptions'])
        
    def test_add_radio_selected_ignored_if_not_option(self):
        builder = TemplateBuilder("myTemplate")      
        builder.radio("r1", ['a', 'b', 'c'], 'XXXX')
        self.assertFalse('selectedOptions' in builder._fields()[0])
        
    def test_add_choice(self):
        builder = TemplateBuilder("myTemplate")      
        builder.choice("r1", ['a', 'b', 'c'], ['a'])
        self.assertEqual(1, builder.field_count())
        self.assertEqual(['a'], builder._fields()[0]['selectedOptions'])
        
    def test_add_choice_selected_ignored_if_not_option(self):
        builder = TemplateBuilder("myTemplate")      
        builder.choice("r1", ['a', 'b', 'c'], ['XXXX'])
        self.assertFalse('selectedOptions' in builder._fields()[0])    
        
    def test_add_text_field(self):
        builder = TemplateBuilder("myTemplate")      
        builder.text("textfield", "defaultVal")
        self.assertEqual(1, builder.field_count())
        
    def test_add_string_field(self):
        builder = TemplateBuilder("myTemplate")      
        builder.string("stringfield", "defaultVal")
        self.assertEqual(1, builder.field_count())
    
    def test_add_number_field(self):
        builder = TemplateBuilder("myTemplate")      
        builder.number("pH", 7.2).number("index", 1)
        self.assertEqual(2, builder.field_count())
        
    def test_add_number_field_requires_number(self):
        builder = TemplateBuilder("myTemplate")      
        
        self.assertRaises(
            ValueError,
            builder.number,
            "pH",
            "XXX",
        )
    def test_add_number_field_no_default(self):
        builder = TemplateBuilder("myTemplate")      
        builder.number("pH").number("index")
        self.assertEqual(2, builder.field_count())
        
        
        