#!/usr/bin/env python3
"""
Unit tests for the ELN and Inventory client methods added or changed for the filesystems:
the URLs, query parameters, bodies and multipart parts they send. No server needed; requests
are intercepted by responses or by mocking the shared session.
"""

import json
import os
import tempfile
import unittest
from io import BytesIO
from unittest import mock

import responses

from rspace_client.eln.eln import ELNClient
from rspace_client.inv.inv import InventoryClient
from rspace_client.tests.exceptions_test import make_response

RSPACE_URL = "https://example.com"
ELN_API = RSPACE_URL + "/api/v1"
INV_API = RSPACE_URL + "/api/inventory/v1"


def named_file(name, content=b"content"):
    f = BytesIO(content)
    f.name = name
    return f


def sent_body(call):
    body = call.request.body
    return body if isinstance(body, bytes) else body.encode()


class ELNClientMethodsTest(unittest.TestCase):
    def setUp(self):
        self.client = ELNClient(RSPACE_URL, "fake-api-key")

    def tearDown(self):
        self.client.close()

    @responses.activate
    def test_delete_document_requests_a_single_slash_url(self):
        # regression: doDelete used to build //documents/5
        responses.add(responses.DELETE, ELN_API + "/documents/5", status=204)
        self.client.delete_document(5)
        self.assertEqual(ELN_API + "/documents/5", responses.calls[0].request.url)

    @responses.activate
    def test_doDelete_tolerates_a_leading_slash_on_the_path(self):
        responses.add(responses.DELETE, ELN_API + "/forms/3", status=204)
        self.client.doDelete("/forms", 3)
        self.client.doDelete("forms", "FM3")
        self.assertEqual(
            [ELN_API + "/forms/3"] * 2, [c.request.url for c in responses.calls]
        )

    @responses.activate
    def test_upload_file_uses_the_given_filename(self):
        responses.add(responses.POST, ELN_API + "/files", json={"id": 1})
        self.client.upload_file(named_file("/tmp/original.bin"), filename="x.txt")
        body = sent_body(responses.calls[0])
        self.assertIn(b'filename="x.txt"', body)
        self.assertNotIn(b"original.bin", body)

    @responses.activate
    def test_upload_file_defaults_to_the_file_objects_name(self):
        responses.add(responses.POST, ELN_API + "/files", json={"id": 1})
        self.client.upload_file(named_file("/tmp/original.bin"))
        self.assertIn(b'filename="original.bin"', sent_body(responses.calls[0]))

    @responses.activate
    def test_list_folder_tree_sends_page_size_only_when_given(self):
        responses.add(responses.GET, ELN_API + "/folders/tree/7", json={})
        self.client.list_folder_tree(7, page_size=5)
        self.client.list_folder_tree(7)
        with_size, without = (c.request.url for c in responses.calls)
        self.assertIn("pageSize=5", with_size)
        self.assertNotIn("pageSize", without)

    def test_failed_export_job_reports_the_servers_error_details(self):
        # regression: the FAILED branch used to drop the message and errors list
        failed = {
            "status": "FAILED",
            "result": {"message": "disk full", "errors": ["e1", "e2"]},
        }
        with (
            tempfile.TemporaryDirectory() as tmp,
            mock.patch.object(self.client, "get_job_status", return_value=failed),
        ):
            log = os.path.join(tmp, "progress.log")
            with self.assertRaises(ELNClient.ApiError) as ctx:
                self.client._wait_till_complete_then_download(
                    1, tmp, wait_between_requests=0, progress_log=log
                )
            with open(log) as f:
                logged = f.read()
        for text in (str(ctx.exception), logged):
            self.assertIn("Export job failed", text)
            self.assertIn("disk full", text)
            self.assertIn("e1, e2", text)


class InventoryClientMethodsTest(unittest.TestCase):
    def setUp(self):
        self.client = InventoryClient(RSPACE_URL, "fake-api-key")

    def tearDown(self):
        self.client.close()

    @responses.activate
    def test_upload_attachment_uses_the_given_filename_and_names_the_parent(self):
        responses.add(responses.POST, INV_API + "/files", json={"id": 1})
        self.client.upload_attachment_by_global_id(
            "SA1", named_file("/tmp/original.bin"), filename="x.txt"
        )
        body = sent_body(responses.calls[0])
        self.assertIn(b'filename="x.txt"', body)
        self.assertIn(json.dumps({"parentGlobalId": "SA1"}).encode(), body)

    @responses.activate
    def test_get_workbench_by_id_accepts_global_and_numeric_ids(self):
        url = INV_API + "/workbenches/64"
        responses.add(responses.GET, url, json={})
        self.client.get_workbench_by_id("BE64")
        self.client.get_workbench_by_id(64)
        self.client.get_workbench_by_id(64, include_content=True)
        self.assertEqual(
            [
                url + "?includeContent=false",
                url + "?includeContent=false",
                url + "?includeContent=true",
            ],
            [c.request.url for c in responses.calls],
        )

    @responses.activate
    def test_attach_gallery_file_posts_both_global_ids(self):
        responses.add(responses.POST, INV_API + "/attachments", json={"id": 1})
        self.client.attach_gallery_file_by_global_id("SA1", "GL2")
        self.assertEqual(
            {"parentGlobalId": "SA1", "mediaFileGlobalId": "GL2"},
            json.loads(responses.calls[0].request.body),
        )

    def test_csv_parse_goes_through_the_shared_session(self):
        ok = make_response(200, json_body={})
        with (
            mock.patch.object(self.client._session, "post", return_value=ok) as post,
            mock.patch("requests.post") as bare_post,
        ):
            self.client.parse_csv_import_file(named_file("samples.csv"), "SAMPLES")
        post.assert_called_once()
        self.assertEqual(INV_API + "/import/parseFile", post.call_args.args[0])
        self.assertFalse(post.call_args.kwargs["allow_redirects"])
        self.assertEqual(self.client.timeout, post.call_args.kwargs["timeout"])
        bare_post.assert_not_called()


if __name__ == "__main__":
    unittest.main()
