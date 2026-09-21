"""
PyFilesystem opener so that ``fs.open_fs("rspace://my.rspace.host")`` returns an
``RSpaceFilesystem``.

The URL never carries the API key. The host is taken from
the URL and the key only from the ``RSPACE_API_KEY`` environment variable. A URL with
a ``user:password@`` component is rejected outright, and the URL cannot name another
variable: a URL is often supplied by someone other than the person whose environment
it is opened in, and must not be able to choose which secret leaves the machine.

URL forms:
    rspace://my.rspace.host                      https, read-only, paths are record names
    rspace://localhost:8080?scheme=http          plain http, accepted for loopback hosts only
    rspace://my.rspace.host?path_style=labelled  'Name [GID]' segments
    rspace://my.rspace.host?path_style=id        bare global-ID segments
    rspace://my.rspace.host?writable=1&allow_delete=1

``fs.open_fs(url, writeable=True)`` also enables writes.
"""
from __future__ import annotations

import os

from fs.opener import Opener, registry
from fs.opener.errors import OpenerError

from .rspace import RSpaceFilesystem

KEY_ENV = "RSPACE_API_KEY"
DEFAULT_KEY_ENV = KEY_ENV  # historical name
_TRUE = ("1", "true", "yes", "on")
#: The only hosts plain http may be used with: a development server on this machine. Over
#: the network the key would travel in clear text.
LOOPBACK_HOSTS = ("localhost", "127.0.0.1", "::1", "[::1]")


def _hostname(host: str) -> str:
    """'localhost:8080' -> 'localhost'; '[::1]:8080' -> '::1'."""
    if host.startswith("["):
        return host[1:host.find("]")]
    return host.rsplit(":", 1)[0] if host.count(":") == 1 else host


def _flag(params, name: str) -> bool:
    return str(params.get(name, "")).lower() in _TRUE


class RSpaceOpener(Opener):
    protocols = ["rspace"]

    def open_fs(self, fs_url, parse_result, writeable, create, cwd):
        if parse_result.username or parse_result.password:
            raise OpenerError(
                "rspace:// URLs must not contain credentials; put the API key in the "
                f"{DEFAULT_KEY_ENV} environment variable instead")
        host = (parse_result.resource or "").strip("/")
        if not host:
            raise OpenerError("rspace:// URL needs a host, e.g. rspace://my.rspace.host")
        params = parse_result.params or {}
        if "api_key_env" in params:
            raise OpenerError(
                "rspace:// URLs cannot choose the environment variable holding the key; "
                f"the key is read from {KEY_ENV} only")
        api_key = os.environ.get(KEY_ENV)
        if not api_key:
            raise OpenerError(f"no API key: set the {KEY_ENV} environment variable")
        scheme = params.get("scheme", "https")
        if scheme not in ("http", "https"):
            raise OpenerError(f"scheme must be http or https, got {scheme!r}")
        if scheme == "http" and _hostname(host) not in LOOPBACK_HOSTS:
            raise OpenerError(
                f"scheme=http is only accepted for a local development server "
                f"({', '.join(LOOPBACK_HOSTS[:3])}); {host!r} would receive the API key in clear text")
        try:
            return RSpaceFilesystem(
                f"{scheme}://{host}", api_key,
                writable=bool(writeable) or _flag(params, "writable"),
                allow_delete=_flag(params, "allow_delete"),
                path_style=params.get("path_style", "name"),
            )
        except ValueError as exc:  # a bad path_style is a bad URL, not a crash
            raise OpenerError(f"invalid rspace:// URL parameter: {exc}") from exc


def install() -> None:
    """Register the opener with PyFilesystem (also done via the fs.opener entry point)."""
    registry.install(RSpaceOpener)


install()
