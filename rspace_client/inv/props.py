#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Fri Jan 14 21:43:11 2022

@author: richard
"""
import re

class AbsValidator:
    def validate(self, item):
        pass


class Number(AbsValidator):
    def validate(self, value):
        if not isinstance(value, (int, float)):
            raise TypeError(f'Expected {value!r} to be an int or float')
            
class String (AbsValidator):
    def validate(self, value):
        if not isinstance(value, str):
            raise TypeError(f'Expected {value!r} to be a string')
            
class OneOf(AbsValidator):
    def __init__(self, options):
        self.options = options
    def validate(self,  value):
        if not value in self.options:
            raise TypeError(f"Expected {value!r} to be one of [{', '.join(self.options)}]")

class AllOf(AbsValidator):
    def __init__(self, options):
        self.options = options
    def validate(self,  chosen):
        if not all ([c in self.options for c in chosen]):
            raise TypeError(f"Expected all chosen items {chosen!r} to be in [{', '.join(self.options)}]")
            
class SampleBuilder:
    
    def name(self, name):
        self.name = name
        
    def description(self, description):
        self.description = description
            
    def tags(self, tags):
        self.tags = tags
            
class Builder:
    
    def sanitize_name(name):
        return re.sub(r'[^\w]+', '_', name).lower()
    
    
    def build(self, sample_template):
        st_name = sample_template['name']   
        class_atts = {}
        class_atts['_san2field'] = {}
        class_atts['_field2san'] = {}
        class_atts['_fields'] = []
        class_atts['_data'] = {}
        defs = sample_template['fields']
        for f_def in defs:    
            field_name= f_def['name']
            sanitized_name = Builder.sanitize_name(field_name)
            handlers = self.build_handlers(f_def, sanitized_name)
    
            class_atts[sanitized_name] = property(*handlers)
            class_atts['_san2field'][sanitized_name] = field_name
            class_atts['_field2san'][field_name] = sanitized_name
            class_atts['_fields'].append(sanitized_name)
        self.clazz = type (st_name, (SampleBuilder,), class_atts)
        return self.clazz
        
    
    def get_validator_for_type(self, f_def):
        t =f_def['type']
        if t == 'String':
            return String()
        elif t == 'Number':
            return Number()
        elif t == 'Radio':
            return OneOf(f_def['options'])
        elif t == 'Choice':
            return AllOf(f_def['options'])
        else:
            return AbsValidator() ## allows anything
    
    def get_doc_for_type(self, f_def, sanitized_name):
        def basic_doc(n, t):
            if f_def['name'] == sanitized_name:
                return f"Property {sanitized_name} of type {t}"
            else:
                return f"Property {sanitized_name} matching sample template field {f_def['name']}"
        
        n = f_def['name']
        t = f_def['type']
        doc = basic_doc(n, t)
        if t == 'Radio' or t == 'Choice':
            return doc + f" Options: {', '.join(f_def['options'])}"
        else:
            return doc

    def build_handlers(self, f_def, sanitized_name):
       
        validator=self.get_validator_for_type(f_def)
        def setter(self, value):
            validator.validate(value)
            self._data[sanitized_name]= value
            
        def getter(self):
            return self._data[sanitized_name]
        
        def deleter(self):
            del(self.data[sanitized_name])        

        return (getter, setter, deleter, self.get_doc_for_type(f_def, sanitized_name))
            
            
st = {'name': 'Enzyme',
         'fields' : [ 
        {'name': 'comment', 'type': 'String'}, 
        {'name': 'p H', 'type': 'Number'},
        {'name': 'source', 'type':'Radio','options':['Commercial', 'Academic']},
        {'name': 'supplier', 'type':'Choice','options':['NEB', 'BM', 'Sigma']}
        ]
    }


b = Builder()
clazz = b.build(st)
inst = b.clazz()


