# -*- coding: utf-8 -*-
from  typing import Optional, Sequence, Union, List
from urllib.parse import urlparse
import numbers
import datetime as dt
import sys

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
    
    def date(self, name: str, isodate: Union[dt.date, dt.datetime, str]):
        """

        Parameters
        ----------
        name : str
            The field name.
        isodate : Union[dt.date, dt.datetime, str]
            Either a datetime.dateime, a datetime.date, or an ISO-8601 string.
        Raises
        ------
        ValueError
            if string  value is not an ISO8601 date (e.g. 2022-01-27)

        Returns
        -------
        This object for chaining

        """
        f = self._set_name(name, "Date")
        defaultDate = None
        ## these conditions must be in order
        if isinstance(isodate, dt.datetime):
            defaultDate = isodate.date().isoformat()
        elif isinstance(isodate, dt.date):
            defaultDate = isodate.isoformat()
        elif isinstance(isodate, str):
            defaultDate = dt.datetime.strptime(isodate,  '%Y-%m-%d').date().isoformat()
        if defaultDate is not None:
            f['content'] = defaultDate
        self.fields.append(f)
        return self
    
    def time(self, name: str, isotime: Union[dt.date, dt.time, str]):
        """

        Parameters
        ----------
        name : str
            The field name.
        isodate : Union[dt.time, dt.datetime, str]
            Either a datetime.datetime, a datetime.time, or an ISO-8601 string.
        Raises
        ------
        ValueError
            if string  value is not an ISO8601 time (e.g. 12:05:36)

        Returns
        -------
        This object for chaining

        """
        f = self._set_name(name, "Time")
        defaultTime = None
        ## these conditions must be in order
        if isinstance(isotime, dt.datetime):
            defaultTime = isotime.time().isoformat()
        elif isinstance(isotime, dt.time):
            defaultTime = isotime.isoformat()
        elif isinstance(isotime, str):
            defaultTime = dt.time.fromisoformat(isotime).isoformat()
        if defaultTime is not None:
            f['content'] = defaultTime
        self.fields.append(f)
        return self
    
    def attachment(self, name: str, desc:str = None):
        """
        Parameters
        ----------
        name : str
            The field name.
        desc : str, optional
           An optional description of the file to upload.

        Returns
        -------
        This object for chaining 

        """
        f = self._set_name(name, "Attachment")
        if desc is not None and  len(desc) > 0 and len(str.strip(desc)) > 0:
            f['content'] = desc
        self.fields.append(f)
        return self
    
    def uri(self, name: str, uri: str = None):
        """
        Parameters
        ----------
        name : str
            The field name.
        uri : str, optional
           An optional default URI

        Returns
        -------
        This object for chaining 
        Raises
        ------
        ValueError if URI is not parsable into a URI

        """
        f = self._set_name(name, "Uri")
        if uri is not None and len(uri) > 0 and len(str.strip(uri)) > 0:
            parsed_uri = urlparse(uri)
            f['content'] = uri
        self.fields.append(f)
        return self
    
    
    
    def field_count(self):
        return len(self.fields)
    
    
    def _fields(self):
        return self.fields
            
        