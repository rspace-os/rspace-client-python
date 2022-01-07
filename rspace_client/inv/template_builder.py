# -*- coding: utf-8 -*-
from  typing import Optional, Sequence, Union, List
import numbers

class TemplateBuilder:
    
    numeric = Union[int, float]
    
    def __init__(self, name):
        
        self.name = name
        self.fields = []
        
    def _set_name(self, name: str, f_type: str):
        if len(name) ==0:
            raise ValueError("Name cannot be empty or None")
        return  { "name": name, "type": f_type}
        
    def radio(self, name: str, options: List, selected: str = None):
        """
        Parameters
        ----------
        name : str
            The field name.
        options : List
            A list of radio options.
        selected : str, optional
            An optional string indicating a radio option that should be selected
            by default. If this string is not in the 'options' List, it will be ignored

        """
        f = self._set_name(name,"Radio")
        f["definition"]= {
                "options" : options
               }
        
        if len(selected) > 0 and selected in options:
            f['selectedOptions']=[selected]
    
        self.fields.append(f)
        return self
    
    def choice(self, name: str, options: List, selected: List = None):
        """
        Parameters
        ----------
        name : str
            The field name.
        options : List
            A list of choice options.
        selected : List, optional
            An optional list of options that should be selected. If items in 
            this list are not in the 'options' List, they will be ignored

        """
        f = self._set_name(name,"Choice")
        
        f["definition"]= {
                "options" : options
               }
            
        
        if len(selected) > 0:
            selected = [x for x in selected if x in options]
            if len(selected) > 0:
                f['selectedOptions']=selected
    
        self.fields.append(f)
        return self
    
    def string(self, name: str, default: str = None):
        f = self._set_name(name,"String")
        if default is not None:
            f['content'] = default
        self.fields.append(f)
        return self
            
    def text(self, name: str, default: str = None):
        f = self._set_name(name,"Text")
        if default is not None:
            f['content'] = default
        self.fields.append(f)
        return self
        
    def number(self,  name: str, default: numeric = None):
        """
        Parameters
        ----------
        name : str
            The field's name.
        default : numeric, optional
            A default numeric value for the field.

        Raises
        ------
        ValueError
            if default value is not a number (integer or float).

        Returns
        -------
        This object for chaining

        """
        f = self._set_name(name,"Number")
        if default is not None:
            if  isinstance(default, numbers.Number):
                f['content'] = default
            else:
                raise ValueError(f"Numeric field requires number but was '{default}'")
        self.fields.append(f)
            
        return self
    ## TODO date, time, URI, attachment?
    
    def date(self, name: str, date):
        f = self._set_name(name,"Date")
        self.fields.append(f)
        return self
    
    def field_count(self):
        return len(self.fields)
    
    
    def _fields(self):
        return self.fields
            
        