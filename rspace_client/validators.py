class AbsValidator:
    def validate(self, item):
        pass


class Number(AbsValidator):
    def validate(self, value):
        if not isinstance(value, (int, float)):
            raise TypeError(f"Expected {value!r} to be an int or float")


class String(AbsValidator):
    def validate(self, value):
        if not isinstance(value, str):
            raise TypeError(f"Expected {value!r} to be a string")


class OneOf(AbsValidator):
    """
      Validates that argument is one of a list of items passed into constructor
    """
    def __init__(self, options):
        self.options = options

    def validate(self, value: str):
        if not isinstance(value, str) or not value in self.options:
            raise TypeError(
                f"Expected {value!r} to be one of [{', '.join(self.options)}]"
            )


class AllOf(AbsValidator):
    """
      Validates that all items in the argument  are in the list of items passed into constructor
    """
    def __init__(self, options):
        self.options = options

    def validate(self, chosen):
        if not isinstance(chosen, list) or  not all([c in self.options for c in chosen]):
            raise TypeError(
                f"Expected all chosen items {chosen!r} to be in [{', '.join(self.options)}]"
            )# -*- coding: utf-8 -*-

