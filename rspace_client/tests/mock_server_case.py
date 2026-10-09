"""
Shared fixture for the offline filesystem tests.

The embedded mock RSpace (``rspace_client/tests/mock_rspace``) is started once per process,
by the first test class that needs it, and kept until exit; every ``MockServerTestCase``
begins each test from the stock fixtures (``server.reset()``). One server rather than one
per class, because the suite used to spend most of its wall time in ``serve_forever``
shutdowns.
"""
import atexit
import unittest
from typing import Optional, Tuple

import requests

from rspace_client.fs.paths import last_segment
from rspace_client.tests.mock_rspace.server import MockRSpaceServer, run_in_thread

_server: Optional[Tuple[MockRSpaceServer, str]] = None


def shared_server() -> Tuple[MockRSpaceServer, str]:
    global _server
    if _server is None:
        _server = run_in_thread()
        atexit.register(lambda: (_server[0].shutdown(), _server[0].server_close()))
    return _server


def names(fs, path):
    """The path segments of a directory's children, in listing order (fsspec's ``name`` is
    the full path)."""
    return [last_segment(n) for n in fs.ls(path, detail=False)]


def segments(entries):
    """The last path segment of each entry (dict) or path (str)."""
    return [last_segment(e["name"] if isinstance(e, dict) else e) for e in entries]


class MockServerTestCase(unittest.TestCase):

    server: MockRSpaceServer
    url: str

    @classmethod
    def setUpClass(cls):
        cls.server, cls.url = shared_server()

    def setUp(self):
        self.server.reset()

    def calls(self) -> int:
        """API requests the mock has served since the last reset, for the tests that
        assert a listing costs one call per directory."""
        return requests.get(f"{self.url}/__mock/stats").json()["requests"]
