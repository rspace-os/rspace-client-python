"""
pytest hooks for the offline test suite.

One mock RSpace server (``rspace_client/tests/mock_rspace``) serves the whole
session. It is started here and handed to :mod:`rspace_client.tests.mock_server_case`,
whose ``MockServerTestCase`` resets its fixtures before every test; the old
one-server-per-class arrangement spent most of the suite's wall time in seven
``serve_forever`` shutdowns.
"""
import pytest

from rspace_client.tests import mock_server_case
from rspace_client.tests.mock_rspace.server import run_in_thread


@pytest.fixture(scope="session", autouse=True)
def shared_mock_server():
    server, url = run_in_thread()
    mock_server_case.install_shared_server(server, url)
    try:
        yield server
    finally:
        mock_server_case.install_shared_server(None, None)
        server.shutdown()
        server.server_close()
