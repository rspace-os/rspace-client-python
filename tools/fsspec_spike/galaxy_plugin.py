"""PROTOTYPE: a Galaxy FsspecFilesSource over the spike. Galaxy discovers plugins by walking
galaxy.files.sources and reading ``__all__``, so to run it copy this file into that package
(for example in a venv with ``pip install galaxy-files``) and configure
``{"type": "rspace_fsspec_spike", "endpoint": ..., "api_key": ..., "fetch_sizes": true}``.
Verified 2026-09-21: list, glob search, recursive list, realize_to and write_from pass against
the mock server; without fetch_sizes Galaxy fails on ``int(None)`` for file sizes."""
from typing import Union

from galaxy.files.models import FilesSourceRuntimeContext
from galaxy.util.config_templates import TemplateExpansion

from ._fsspec import (CacheOptionsDictType, FsspecBaseFileSourceConfiguration,
                      FsspecBaseFileSourceTemplateConfiguration, FsspecFilesSource)
from fsspec_gallery import GalleryFileSystem  # put tools/fsspec_spike on sys.path


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

    def _open_fs(self, context: FilesSourceRuntimeContext[Conf], cache_options: CacheOptionsDictType):
        c = context.config
        return GalleryFileSystem(c.endpoint, c.api_key, writable=True, fetch_sizes=c.fetch_sizes, **cache_options)

    def _to_filesystem_path(self, path, config):
        return "" if path in ("", "/") else path.lstrip("/")

    def _adapt_entry_path(self, filesystem_path, config):
        return "/" if not filesystem_path else "/" + filesystem_path.lstrip("/")


__all__ = ("RSpaceFsspecSpikeSource",)
