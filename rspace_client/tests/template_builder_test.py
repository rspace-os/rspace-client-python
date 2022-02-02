#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Mon Jun  7 08:38:55 2021

@author: richard
"""


from rspace_client.inv.template_builder import TemplateBuilder
import unittest
import datetime as dt

builder = None


class TemplateBuilderTest(unittest.TestCase):
    def test_invalid_unit(self):
        self.assertRaises(
            ValueError,
            TemplateBuilder,
            "name",
            "unknownUnit",
        )

    def test_add_radio(self):
        builder = TemplateBuilder("myTemplate", "ml")
        builder.radio("r1", ["a", "b", "c"], "a")
        self.assertEqual(1, builder.field_count())
        self.assertEqual(["a"], builder._fields()[0]["selectedOptions"])

    def test_add_radio_selected_ignored_if_not_option(self):
        builder = TemplateBuilder("myTemplate", "ml")
        builder.radio("r1", ["a", "b", "c"], "XXXX")
        self.assertFalse("selectedOptions" in builder._fields()[0])

    def test_add_radio_with_no_selection(self):
        builder = TemplateBuilder("myTemplate", "ml")
        builder.radio("r1", options=["a", "b", "c"])
        self.assertFalse("selectedOptions" in builder._fields()[0])

    def test_add_choice(self):
        builder = TemplateBuilder("myTemplate", "ml")
        builder.choice("r1", ["a", "b", "c"], ["a"])
        self.assertEqual(1, builder.field_count())
        self.assertEqual(["a"], builder._fields()[0]["selectedOptions"])

    def test_add_choice_selected_ignored_if_not_option(self):
        builder = TemplateBuilder("myTemplate", "ml")
        builder.choice("r1", ["a", "b", "c"], ["XXXX"])
        self.assertFalse("selectedOptions" in builder._fields()[0])

    def test_add_text_field(self):
        builder = TemplateBuilder("myTemplate", "ml")
        builder.text("textfield", "defaultVal")
        self.assertEqual(1, builder.field_count())

    def test_add_string_field(self):
        builder = TemplateBuilder("myTemplate", "ml")
        builder.string("stringfield", "defaultVal")
        self.assertEqual(1, builder.field_count())

    def test_add_number_field(self):
        builder = TemplateBuilder("myTemplate", "ml")
        builder.number("pH", 7.2).number("index", 1)
        self.assertEqual(2, builder.field_count())

    def test_add_number_field_requires_number(self):
        builder = TemplateBuilder("myTemplate", "ml")

        self.assertRaises(
            ValueError,
            builder.number,
            "pH",
            "XXX",
        )

    def test_add_number_field_no_default(self):
        builder = TemplateBuilder("myTemplate", "ml")
        builder.number("pH").number("index")
        self.assertEqual(2, builder.field_count())

    def test_name_required(self):
        builder = TemplateBuilder("myTemplate", "ml")
        self.assertRaises(
            ValueError,
            builder.number,
            "",
        )

    def test_add_date(self):
        builder = TemplateBuilder("myTemplate", "ml")
        builder.date("d", dt.date(2021, 10, 26))
        self.assertEqual(1, builder.field_count())

        builder.date("fromstr", "2021-10-26")
        self.assertEqual(2, builder.field_count())

        builder.date("fromdate-time", dt.datetime.strptime("2021-10-26", "%Y-%m-%d"))
        self.assertEqual(3, builder.field_count())
        contents = [a["content"] for a in builder._fields()]
        self.assertTrue(all(d == "2021-10-26" for d in contents))

    def test_add_time(self):
        builder = TemplateBuilder("myTemplate", "ml")
        builder.time("d", dt.time(2, 30, 59))
        self.assertEqual(1, builder.field_count())

        builder.time("fromstr", "02:30:59")
        self.assertEqual(2, builder.field_count())

        builder.time("fromdate-time", dt.datetime(2021, 10, 26, 2, 30, 59))
        self.assertEqual(3, builder.field_count())
        contents = [a["content"] for a in builder._fields()]
        self.assertTrue(all(d == "02:30:59" for d in contents))

    def test_add_attachment(self):
        builder = TemplateBuilder("myTemplate", "ml")
        desc = "A PDF of a CoSH form"
        builder.attachment("Safety data", desc)
        self.assertEqual(desc, builder._fields()[0]["content"])

        builder.attachment("Safety data")
        self.assertFalse("content" in builder._fields()[1])

        builder.attachment("Safety data", "")
        self.assertFalse("content" in builder._fields()[1])

        builder.attachment("Safety data", "   ")
        self.assertFalse("content" in builder._fields()[2])

    def test_add_uri(self):
        builder = TemplateBuilder("myTemplate", "ml")
        builder.uri("A URI", "https://www.google.com")
        builder.uri("no default")
        self.assertEqual(2, builder.field_count())
        self.assertEqual("https://www.google.com", builder._fields()[0]["content"])
        self.assertRaises(
            ValueError,
            builder.uri,
            "name",
            "aa://www.goog[le.com:XXXX",
        )

    def test_build(self):
        builder = TemplateBuilder("water sample", "ml").text("notes").number("pH", 7)
        to_post = builder.build()
