#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Unit tests for the exception hierarchy and ClientBase._handle_response.
"""
import json
import unittest

import requests

import rspace_client
from rspace_client.client_base import ClientBase
from rspace_client.exceptions import (
    ApiError,
    AuthenticationError,
    NoSuchLinkRel,
    RSpaceConnectionError,
    RSpaceError,
)


def make_response(status_code, json_body=None, text_body=None, content_type=None):
    """
    Builds a real requests.Response without a network call.
    """
    response = requests.models.Response()
    response.status_code = status_code
    if json_body is not None:
        response._content = json.dumps(json_body).encode("utf-8")
        response.headers["Content-Type"] = "application/json"
    elif text_body is not None:
        response._content = text_body.encode("utf-8")
    else:
        response._content = b""
    if content_type is not None:
        response.headers["Content-Type"] = content_type
    return response


class HandleResponseTest(unittest.TestCase):
    def test_success_json_returns_dict(self):
        response = make_response(200, json_body={"id": 1})
        self.assertEqual({"id": 1}, ClientBase._handle_response(response))

    def test_success_text_returns_text(self):
        response = make_response(200, text_body="plain text", content_type="text/plain")
        self.assertEqual("plain text", ClientBase._handle_response(response))

    def test_success_empty_returns_response(self):
        response = make_response(204)
        self.assertIs(response, ClientBase._handle_response(response))

    def test_json_error_raises_api_error_with_details(self):
        response = make_response(
            400, json_body={"message": "bad request", "errors": ["name is required"]}
        )
        with self.assertRaises(ApiError) as cm:
            ClientBase._handle_response(response)
        self.assertEqual(400, cm.exception.response_status_code)
        self.assertIs(response, cm.exception.response)
        self.assertIn("bad request", str(cm.exception))
        self.assertIn("name is required", str(cm.exception))

    def test_error_without_content_type_header_raises_api_error(self):
        # previously raised KeyError when the Content-Type header was missing
        response = make_response(500, text_body="Internal Server Error")
        with self.assertRaises(ApiError) as cm:
            ClientBase._handle_response(response)
        self.assertEqual(500, cm.exception.response_status_code)

    def test_error_with_malformed_json_body_raises_api_error(self):
        # Content-Type says JSON but the body does not parse
        response = make_response(
            502, text_body="<html>Bad Gateway</html>", content_type="application/json"
        )
        with self.assertRaises(ApiError) as cm:
            ClientBase._handle_response(response)
        self.assertIn("Bad Gateway", str(cm.exception))

    def test_401_json_raises_authentication_error(self):
        response = make_response(401, json_body={"message": "invalid key"})
        with self.assertRaises(AuthenticationError) as cm:
            ClientBase._handle_response(response)
        self.assertIn("invalid key", str(cm.exception))

    def test_401_non_json_raises_authentication_error(self):
        # previously crashed with a JSON decode error, e.g. a 401 from a proxy
        response = make_response(
            401, text_body="<html>Unauthorized</html>", content_type="text/html"
        )
        with self.assertRaises(AuthenticationError):
            ClientBase._handle_response(response)


class ExceptionHierarchyTest(unittest.TestCase):
    def test_all_inherit_from_rspace_error(self):
        for exception_class in (
            ApiError,
            AuthenticationError,
            NoSuchLinkRel,
            RSpaceConnectionError,
        ):
            self.assertTrue(issubclass(exception_class, RSpaceError))

    def test_deprecated_nested_aliases_are_same_classes(self):
        self.assertIs(ClientBase.ApiError, ApiError)
        self.assertIs(ClientBase.AuthenticationError, AuthenticationError)
        self.assertIs(ClientBase.NoSuchLinkRel, NoSuchLinkRel)
        self.assertIs(ClientBase.ConnectionError, RSpaceConnectionError)

    def test_catching_via_deprecated_alias_still_works(self):
        with self.assertRaises(ClientBase.ApiError):
            raise ApiError("boom", response_status_code=418)

    def test_exceptions_exported_from_package_root(self):
        self.assertIs(rspace_client.ApiError, ApiError)
        self.assertIs(rspace_client.RSpaceError, RSpaceError)

    def test_api_error_carries_response_object(self):
        response = make_response(503, text_body="unavailable")
        error = ApiError("failed", response_status_code=503, response=response)
        self.assertIs(response, error.response)
        self.assertEqual(503, error.response_status_code)


if __name__ == "__main__":
    unittest.main()
