import datetime as dt
from urllib.parse import urlparse


class AbsValidator:
    def validate(self, item):
        pass

    def raise_type_error(self, value, expected_type: str):
        raise TypeError(f"Expected {value!r} to be {expected_type}")


class Number(AbsValidator):
    def validate(self, value):
        if not isinstance(value, (int, float)):
            self.raise_type_error(value, "an int or float")


class String(AbsValidator):
    def validate(self, value):
        if not isinstance(value, str):
            self.raise_type_error(value, "a string")


class Date(AbsValidator):
    def validate(self, value):
        if not isinstance(value, dt.date) and not isinstance(value, dt.datetime):
            self.raise_type_error(value, "a datetime or date")


class Time(AbsValidator):
    def validate(self, value):
        if not isinstance(value, dt.datetime) and not isinstance(value, dt.time):
            self.raise_type_error(value, "a datetime or date")


class URL(AbsValidator):
    def validate(self, item):
        if isinstance(item, str):
            try:
                urlparse(item)
            except:
                raise TypeError("{type(item)} {item!r} could not be parsed")

        else:
            self.raise_type_error(item, "a URI string")


class OneOf(AbsValidator):
    """
    Validates that argument is one of a list of items passed into constructor
    """

    def __init__(self, options):
        self.options = options

    def validate(self, value: str):
        if not isinstance(value, str) or not value in self.options:
            self.raise_type_error(value, f"to be one of [{', '.join(self.options)}]")


class AllOf(AbsValidator):
    """
    Validates that all items in the argument  are in the list of items passed into constructor
    """

    def __init__(self, options):
        self.options = options

    def validate(self, chosen):
        if not isinstance(chosen, list) or not all([c in self.options for c in chosen]):
            raise TypeError(
                f"Expected all chosen items {chosen!r} to be in [{', '.join(self.options)}]"
            )  # -*- coding: utf-8 -*-
