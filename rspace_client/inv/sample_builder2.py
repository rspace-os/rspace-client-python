#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Fri Jan 14 21:43:11 2022

@author: richard
"""
import re
import pprint as p
import datetime as dt


import rspace_client.validators as v


class AbsFieldBuilder:
    """
    Base class of dynamically generated SampleTemplate classes
    """

    def to_field_post(self):
        """
         Generates a list of Fields to include in a create_sample POST.

        Returns
        -------
        toPost : list
        An array of FieldPost

        """
        toPost = []
        for f in self._fields:
            if f in self._data:
                f_def = self._san2field[f]
                if f_def["type"].lower() == "choice":
                    toPost.append({"selectedOptions": self._data[f]})
                elif f_def["type"].lower() == "radio":
                    toPost.append({"selectedOptions": [self._data[f]]})
                elif f_def["type"].lower() == "time":
                    t = self._data[f]
                    toPost.append({"content": f"{t.hour}:{t.minute}"})

                else:
                    toPost.append({"content": str(self._data[f])})
            else:
                toPost.append({})

        return toPost


class FieldBuilderGenerator:
    """
    Helper class for creating Python classes from SampleTemplates, to help with
    setting field information into Samples.
    """

    def generate_class(self, sample_template):
        """
        Generates a Python class where attributes and validation is generated
        from the supplied SampleTemplate dict. The SampleTemplate should be the response from a
        POST to create a new sampleTemplate or a GET to retrieve SampleTemplate by its Id.

        Use of this class helps to provide type-saety and argument validation before submitting
        a create_sample POST to the RSpace server.

        Property names are generated from template field names, converting all characters to lower-case and
        replacing groups of non-alphanumeric characters with '_'.
        Leaing numbers are prefixed with 'n', e.g.

        Sample Template Field Name     ->    Python property name

        pH  -> ph
        Notes and Queries -> notes_and_queries
        5' sequence -> n5_sequence

        Validators and documentation for each property are generated from the fied definition , e.g:
        """

        st_name = sample_template["name"]
        class_atts = {}
        _san2field = {}
        _fields = []
        class_atts["_data"] = {}

        defs = sample_template["fields"]
        for f_def in defs:
            field_name = f_def["name"]

            sanitized_name = FieldBuilderGenerator._sanitize_name(field_name)
            handlers = self._build_handlers(f_def, sanitized_name)

            class_atts[sanitized_name] = property(*handlers)
            _san2field[sanitized_name] = f_def
            _fields.append(sanitized_name)
        self.clazz = type(st_name, (AbsFieldBuilder,), class_atts)
        self.clazz._fields = _fields
        self.clazz._san2field = _san2field
        return self.clazz

    def _sanitize_name(name):

        s1 = re.sub(r"[^\w]+", "_", name).lower()
        return re.sub(r"(^\d+)", r"n\1", s1)

    def _get_validator_for_type(self, f_def):
        t = f_def["type"].lower()
        if t == "string" or t == "text" or t == "attachment":
            return v.String()
        elif t == "aumber":
            return v.Number()
        ## the api varies between 1.73 and 1.74
        elif t == "radio":
            options = []
            if "options" in f_def:
                options = f_def["options"]
            elif "definition" in f_def:
                options = f_def["definition"]["options"]
            return v.OneOf(options)
        elif t == "choice":
            options = []
            if "options" in f_def:
                options = f_def["options"]
            elif "definition" in f_def:
                options = f_def["definition"]["options"]
            return v.AllOf(options)
        elif t == "date":
            return v.Date()
        elif t == "time":
            return v.Time()
        else:
            return v.AbsValidator()  ## allows anything

    def _get_doc_for_type(self, f_def, sanitized_name):
        def basic_doc(n, t):
            if f_def["name"] == sanitized_name:
                return f"Property {sanitized_name} of type {t}"
            else:
                return f"Property {sanitized_name} matching sample template field {f_def['name']}"

        n = f_def["name"]
        t = f_def["type"]
        doc = basic_doc(n, t)
        if t == "Radio" or t == "Choice":
            return doc + f" Options: {', '.join(f_def['options'])}"
        else:
            return doc

    def _build_handlers(self, f_def, sanitized_name):

        validator = self._get_validator_for_type(f_def)

        def setter(self, value):
            validator.validate(value)
            self._data[sanitized_name] = value

        def getter(self):
            return self._data[sanitized_name]

        def deleter(self):
            del self.data[sanitized_name]

        return (getter, setter, deleter, self._get_doc_for_type(f_def, sanitized_name))


if __name__ == "__main__":
    st = {
        "name": "Enzyme",
        "fields": [
            {"name": "comment", "type": "String"},
            {"name": "pH", "type": "Number"},
            {"name": "source", "type": "Radio", "options": ["Commercial", "Academic"]},
            {"name": "supplier", "type": "Choice", "options": ["NEB", "BM", "Sigma"]},
            {"name": "5' manufacture Date", "type": "Date"},
            {"name": "manufacture Time", "type": "Time"},
            {"name": "Safety Data", "type": "Attachment"},
        ],
    }
    b = FieldBuilderGenerator()
    Enzyme = b.generate_class(st)
    inst = Enzyme()
    inst.source = "Academic"
    inst.ph = 4.3
    inst.comment = "some comment about the enzyme"
    inst.supplier = ["Sigma", "BM"]
    inst.n5_manufacture_date = dt.date(2001, 2, 3)
    inst.manufacture_time = dt.time(12, 34)
    inst.safety_data = "MyPdf"  # a description of the file. Upload the file separately

    p.pprint(inst.to_field_post())
