"""
Shared fixture for the offline filesystem tests.

The embedded mock RSpace (``rspace_client/tests/mock_rspace``) is started once per
session by ``conftest.py`` and installed here; every ``MockServerTestCase`` subclass
talks to that one server and begins each test from the stock fixtures
(``server.reset()``). Under plain ``python -m unittest`` no conftest runs, so the
first class to need a server starts one lazily and keeps it for the process.
"""
import atexit
import unittest
from typing import Optional, Tuple

import requests

from rspace_client.tests.mock_rspace.server import MockRSpaceServer, run_in_thread

_shared: Tuple[Optional[MockRSpaceServer], Optional[str]] = (None, None)
_owned: Tuple[Optional[MockRSpaceServer], Optional[str]] = (None, None)


def install_shared_server(server: Optional[MockRSpaceServer], url: Optional[str]) -> None:
    """Called by the pytest session fixture with the session's server, then with None at teardown."""
    global _shared
    _shared = (server, url)


def _stop_owned() -> None:
    server, _ = _owned
    if server is not None:
        server.shutdown()
        server.server_close()


def shared_server() -> Tuple[MockRSpaceServer, str]:
    """The session server if pytest installed one, else a process-wide fallback started on demand."""
    global _owned
    if _shared[0] is not None:
        return _shared  # type: ignore[return-value]
    if _owned[0] is None:
        _owned = run_in_thread()
        atexit.register(_stop_owned)
    return _owned  # type: ignore[return-value]


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
