"""
Exception hierarchy for rspace-client.

All exceptions raised by this library inherit from RSpaceError, so user code
can catch anything the client raises with ``except rspace_client.RSpaceError``.

In earlier releases these lived as nested classes on ClientBase
(e.g. ``ClientBase.ApiError``). Those names remain as aliases of the classes
defined here and will be removed in 3.0.
"""
from typing import Optional

import requests


class RSpaceError(Exception):
    """Base class for all errors raised by rspace-client."""


class RSpaceConnectionError(RSpaceError):
    """Raised when the client cannot connect to the RSpace server."""


class AuthenticationError(RSpaceError):
    """Raised when the server rejects the API key (HTTP 401)."""


class NoSuchLinkRel(RSpaceError):
    """Raised when a requested link rel is not present in a response."""


class ApiError(RSpaceError):
    """
    Raised when the server returns an error response.

    :param error_message: human-readable description of the failure
    :param response_status_code: HTTP status code of the error response
    :param response: the raw requests.Response, when available, so callers
        can inspect headers and body
    """

    def __init__(
        self,
        error_message: str,
        response_status_code: Optional[int] = None,
        response: Optional[requests.Response] = None,
    ):
        super().__init__(error_message)
        self.response_status_code = response_status_code
        self.response = response
