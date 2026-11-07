"""
RSpace API client for interacting with RSpace ELN and Inventory
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("rspace-client")
except PackageNotFoundError:
    __version__ = "unknown"

from .eln.advanced_query_builder import AdvancedQueryBuilder
from .eln.eln import ELNClient
from .eln.field_content import FieldContent
from .exceptions import (
    ApiError,
    AuthenticationError,
    NoSuchLinkRel,
    RSpaceConnectionError,
    RSpaceError,
)
from .inv.inv import InventoryClient
from .utils import createELNClient

__all__ = [
    "ELNClient",
    "InventoryClient",
    "AdvancedQueryBuilder",
    "createELNClient",
    "FieldContent",
    "notebook_sync",
    "RSpaceError",
    "RSpaceConnectionError",
    "AuthenticationError",
    "ApiError",
    "NoSuchLinkRel",
]
