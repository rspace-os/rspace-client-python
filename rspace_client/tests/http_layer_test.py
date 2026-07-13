#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Unit tests for the HTTP layer of ClientBase: session construction, retry
policy, timeout propagation and exception mapping.

The retry loop itself runs inside urllib3 (below the adapter layer that the
responses library mocks), so the retry *policy* is tested directly on
_RSpaceRetry while request/response behavior is tested through responses.
"""
import unittest
from unittest import mock

import requests
import responses

from rspace_client.client_base import (
    ClientBase,
    DEFAULT_MAX_RETRIES,
    DEFAULT_TIMEOUT,
    RETRY_STATUSES,
    _RSpaceRetry,
)
from rspace_client.eln.eln import ELNClient
from rspace_client.exceptions import ApiError, RSpaceConnectionError
from rspace_client.tests.exceptions_test import make_response

RSPACE_URL = "https://example.com"
API_URL = RSPACE_URL + "/api/v1"


def make_retry(**kwargs):
    defaults = dict(
        total=DEFAULT_MAX_RETRIES,
        status_forcelist=RETRY_STATUSES,
        allowed_methods=("GET", "PUT", "DELETE"),
        raise_on_status=False,
    )
    defaults.update(kwargs)
    return _RSpaceRetry(**defaults)


class RetryPolicyTest(unittest.TestCase):
    def test_idempotent_methods_retry_on_all_listed_statuses(self):
        retry = make_retry()
        for method in ("GET", "PUT", "DELETE"):
            for status in RETRY_STATUSES:
                self.assertTrue(
                    retry.is_retry(method, status),
                    "{} {} should be retried".format(method, status),
                )

    def test_post_retries_only_when_server_rejected_before_processing(self):
        retry = make_retry()
        self.assertTrue(retry.is_retry("POST", 429))
        self.assertTrue(retry.is_retry("POST", 503))
        for status in (500, 502, 504):
            self.assertFalse(
                retry.is_retry("POST", status),
                "POST {} must not be retried: the server may have processed "
                "the request, so a replay could create duplicates".format(status),
            )

    def test_success_statuses_are_not_retried(self):
        retry = make_retry()
        for method in ("GET", "POST", "PUT", "DELETE"):
            self.assertFalse(retry.is_retry(method, 200))


class SessionConfigTest(unittest.TestCase):
    def setUp(self):
        self.client = ELNClient(RSPACE_URL, "fake-api-key")

    def tearDown(self):
        self.client.close()

    def test_session_has_api_key_header(self):
        self.assertEqual("fake-api-key", self.client._session.headers["apiKey"])

    def test_retry_adapter_mounted_for_both_schemes(self):
        for scheme in ("https://", "http://"):
            adapter = self.client._session.get_adapter(scheme + "example.com")
            retry = adapter.max_retries
            self.assertIsInstance(retry, _RSpaceRetry)
            self.assertEqual(DEFAULT_MAX_RETRIES, retry.total)
            self.assertFalse(retry.raise_on_status)
            self.assertTrue(retry.respect_retry_after_header)

    def test_client_is_a_context_manager(self):
        with ELNClient(RSPACE_URL, "fake-api-key") as client:
            self.assertIsNotNone(client._session)


class TimeoutPropagationTest(unittest.TestCase):
    def test_default_timeout_passed_to_get(self):
        client = ELNClient(RSPACE_URL, "fake-api-key")
        with mock.patch.object(
            client._session, "get", return_value=make_response(200, json_body={})
        ) as mocked_get:
            client.retrieve_api_results("/status")
        self.assertEqual(DEFAULT_TIMEOUT, mocked_get.call_args.kwargs["timeout"])

    def test_constructor_timeout_passed_to_non_get(self):
        client = ELNClient(RSPACE_URL, "fake-api-key", timeout=(5, 120))
        with mock.patch.object(
            client._session, "request", return_value=make_response(200, json_body={})
        ) as mocked_request:
            client.retrieve_api_results("/forms", request_type="POST")
        self.assertEqual((5, 120), mocked_request.call_args.kwargs["timeout"])


class ExceptionMappingTest(unittest.TestCase):
    def setUp(self):
        self.client = ELNClient(RSPACE_URL, "fake-api-key")

    def tearDown(self):
        self.client.close()

    @responses.activate
    def test_http_error_maps_to_api_error(self):
        responses.add(
            responses.GET,
            API_URL + "/documents",
            json={"message": "not found", "errors": []},
            status=404,
        )
        with self.assertRaises(ApiError) as cm:
            self.client.retrieve_api_results("/documents")
        self.assertEqual(404, cm.exception.response_status_code)

    @responses.activate
    def test_connection_error_maps_to_rspace_connection_error(self):
        responses.add(
            responses.GET,
            API_URL + "/status",
            body=requests.exceptions.ConnectionError("refused"),
        )
        with self.assertRaises(RSpaceConnectionError):
            self.client.retrieve_api_results("/status")

    @responses.activate
    def test_read_timeout_maps_to_rspace_connection_error(self):
        responses.add(
            responses.GET,
            API_URL + "/status",
            body=requests.exceptions.ReadTimeout("timed out"),
        )
        with self.assertRaises(RSpaceConnectionError):
            self.client.retrieve_api_results("/status")

    @responses.activate
    def test_successful_json_call_returns_dict(self):
        responses.add(
            responses.GET, API_URL + "/status", json={"message": "OK"}, status=200
        )
        self.assertEqual({"message": "OK"}, self.client.retrieve_api_results("/status"))


class MultipartHelperTest(unittest.TestCase):
    def setUp(self):
        self.client = ELNClient(RSPACE_URL, "fake-api-key")

    def tearDown(self):
        self.client.close()

    @responses.activate
    def test_upload_success_returns_parsed_json(self):
        responses.add(
            responses.POST, API_URL + "/files", json={"id": 123}, status=200
        )
        result = self.client._post_multipart(
            "/files", files={"file": ("f.txt", b"content")}, data={"folderId": 1}
        )
        self.assertEqual({"id": 123}, result)

    @responses.activate
    def test_upload_error_maps_to_api_error_like_json_calls(self):
        responses.add(
            responses.POST,
            API_URL + "/files",
            json={"message": "file too large", "errors": []},
            status=413,
        )
        with self.assertRaises(ApiError) as cm:
            self.client._post_multipart("/files", files={"file": ("f.txt", b"x")})
        self.assertEqual(413, cm.exception.response_status_code)

    def test_upload_passes_timeout(self):
        with mock.patch.object(
            self.client._session, "post", return_value=make_response(200, json_body={})
        ) as mocked_post:
            self.client._post_multipart("/files", files={"file": ("f.txt", b"x")})
        self.assertEqual(DEFAULT_TIMEOUT, mocked_post.call_args.kwargs["timeout"])


class RawResponseHelperTest(unittest.TestCase):
    def setUp(self):
        self.client = ELNClient(RSPACE_URL, "fake-api-key")

    def tearDown(self):
        self.client.close()

    @responses.activate
    def test_binary_get_returns_raw_response(self):
        responses.add(
            responses.GET,
            API_URL + "/barcodes",
            body=b"\x89PNG binary",
            status=200,
            content_type="image/png",
        )
        response = self.client._get_raw_response(
            API_URL + "/barcodes", accept="image/png"
        )
        self.assertEqual(b"\x89PNG binary", response.content)

    @responses.activate
    def test_binary_get_error_maps_to_api_error(self):
        responses.add(
            responses.GET, API_URL + "/barcodes", body="nope", status=404
        )
        with self.assertRaises(ApiError) as cm:
            self.client._get_raw_response(API_URL + "/barcodes")
        self.assertEqual(404, cm.exception.response_status_code)


if __name__ == "__main__":
    unittest.main()
