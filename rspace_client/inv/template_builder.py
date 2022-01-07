# -*- coding: utf-8 -*-
from  typing import Optional, Sequence, Union, List
import numbers

class TemplateBuilder:
    
    numeric = Union[int, float]
    
    def __init__(self, name):
        
        self.name = name
        self.fields = []
        
    def radio(self, name: str, options: List, selected: str = None):
        f = { "name": name,
              "type": "Radio",
              "definition": {
                "options" : options
               }
            }
        
        if len(selected) > 0 and selected in options:
            f['selectedOptions']=[selected]
    
        self.fields.append(f)
        return self
    
    def choice(self, name: str, options: List, selected: List = None):
        f = { "name": name,
              "type": "Choice",
              "definition": {
                "options" : options
               }
            }
        
        if len(selected) > 0:
            selected = [x for x in selected if x in options]
            if len(selected) > 0:
                f['selectedOptions']=selected
    
        self.fields.append(f)
        return self
    
    def string(self, name: str, default: str = None):
        f = {'name' : name, 'type' : 'String'}
        if default is not None:
            f['content'] = default
        self.fields.append(f)
        return self
            
    def text(self, name: str, default: str = None):
        f = {'name' : name, 'type' : 'Text'}
        if default is not None:
            f['content'] = default
        self.fields.append(f)
        return self
        
    def number(self,  name: str, default: numeric = None):
        f = {'name' : name, 'type' : 'Number'}
        if default is not None:
            if  isinstance(default, numbers.Number):
                f['content'] = default
            else:
                raise ValueError(f"Numeric field requires number but was '{default}'")
        self.fields.append(f)
            
        return self
    
    def field_count(self):
        return len(self.fields)
    
    
    def _fields(self):
        return self.fields
            
        