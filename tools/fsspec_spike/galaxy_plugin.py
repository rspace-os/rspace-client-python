"""PROTOTYPE: a Galaxy FsspecFilesSource over the spike. Galaxy discovers plugins by walking
galaxy.files.sources and reading ``__all__``, so to run it copy this file into that package
(for example in a venv with ``pip install galaxy-files``) and configure
``{"type": "rspace_fsspec_spike", "endpoint": ..., "api_key": ..., "fetch_sizes": true}``.
Verified 2026-09-21 with galaxy-files (current) and 2026-10-06 inside a Galaxy 25.1 container:
list, glob search, recursive list, realize_to and write_from pass against the mock server;
without fetch_sizes Galaxy fails on ``int(None)`` for file sizes. Galaxy 25.1 calls the path
hooks without the ``config`` argument and ``_open_fs`` without ``cache_options``, so the hooks
accept both signatures."""
from typing import Union

from galaxy.files.models import FilesSourceRuntimeContext
from galaxy.util.config_templates import TemplateExpansion

from ._fsspec import (CacheOptionsDictType, FsspecBaseFileSourceConfiguration,
                      FsspecBaseFileSourceTemplateConfiguration, FsspecFilesSource)
from fsspec_gallery import GalleryFileSystem  # in Galaxy: copy fsspec_gallery.py next to this file and import relatively


class Tmpl(FsspecBaseFileSourceTemplateConfiguration):
    endpoint: Union[str, TemplateExpansion]
    api_key: Union[str, TemplateExpansion]
    fetch_sizes: bool = False


class Conf(FsspecBaseFileSourceConfiguration):
    endpoint: str
    api_key: str
    fetch_sizes: bool = False


class RSpaceFsspecSpikeSource(FsspecFilesSource[Tmpl, Conf]):
    plugin_type = "rspace_fsspec_spike"
    required_module = GalleryFileSystem
    required_package = "rspace-client"
    template_config_class = Tmpl
    resolved_config_class = Conf

    def _open_fs(self, context: FilesSourceRuntimeContext[Conf], cache_options: CacheOptionsDictType = None):
        c = context.config
        return GalleryFileSystem(c.endpoint, c.api_key, writable=True, fetch_sizes=c.fetch_sizes, **(cache_options or {}))

    def _to_filesystem_path(self, path, config=None):
        return "" if path in ("", "/") else path.lstrip("/")

    def _adapt_entry_path(self, filesystem_path, config=None):
        return "/" if not filesystem_path else "/" + filesystem_path.lstrip("/")


__all__ = ("RSpaceFsspecSpikeSource",)
