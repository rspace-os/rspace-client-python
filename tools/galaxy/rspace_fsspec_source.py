"""
Reference Galaxy file source for the unified RSpace filesystem, built on Galaxy's
``FsspecFilesSource``. This is the file proposed for ``lib/galaxy/files/sources/rspace.py``
in the Galaxy repository (galaxyproject/galaxy#21832 tracks the move from ``fs`` to fsspec);
it is kept here so it can be tested against this client before that pull request exists.

To try it in a Galaxy checkout or container, copy this file into ``galaxy/files/sources/``
(Galaxy discovers plugins by walking that package and reading ``__all__``) and configure a
source in ``file_sources_conf.yml``:

    - type: rspace_unified
      id: rspace
      label: RSpace
      doc: Gallery, Inventory and Workspace of your RSpace account
      endpoint: https://my.rspace.host
      api_key: ${user.preferences['rspace|api_key']}
      writable: true
      # mounts: gallery,inventory,workspace   (default: all three)
      # path_style: name                      (name | labelled | id)
      # fetch_sizes: true                     (one extra request per Gallery file, Galaxy needs sizes)

Galaxy 25.1 and 26.x differ in how they call the path hooks (with or without a ``config``
argument) and ``_open_fs`` (with or without ``cache_options``); the signatures below accept
both.
"""
from typing import Optional, Union

from galaxy.files.models import FilesSourceRuntimeContext
from galaxy.util.config_templates import TemplateExpansion

from ._fsspec import (
    CacheOptionsDictType,
    FsspecBaseFileSourceConfiguration,
    FsspecBaseFileSourceTemplateConfiguration,
    FsspecFilesSource,
)

try:
    from rspace_client.fs import RSpaceFilesystem
except ImportError:
    RSpaceFilesystem = None


class RSpaceUnifiedFileSourceTemplateConfiguration(FsspecBaseFileSourceTemplateConfiguration):
    endpoint: Union[str, TemplateExpansion]
    api_key: Union[str, TemplateExpansion]
    mounts: Optional[Union[str, TemplateExpansion]] = None
    path_style: Optional[Union[str, TemplateExpansion]] = None
    fetch_sizes: Union[bool, TemplateExpansion] = True


class RSpaceUnifiedFileSourceConfiguration(FsspecBaseFileSourceConfiguration):
    endpoint: str
    api_key: str
    mounts: Optional[str] = None
    path_style: Optional[str] = None
    fetch_sizes: bool = True


class RSpaceUnifiedFilesSource(
    FsspecFilesSource[RSpaceUnifiedFileSourceTemplateConfiguration, RSpaceUnifiedFileSourceConfiguration]
):
    plugin_type = "rspace_unified"
    required_module = RSpaceFilesystem
    required_package = "rspace-client"

    template_config_class = RSpaceUnifiedFileSourceTemplateConfiguration
    resolved_config_class = RSpaceUnifiedFileSourceConfiguration

    def _open_fs(
        self,
        context: FilesSourceRuntimeContext[RSpaceUnifiedFileSourceConfiguration],
        cache_options: Optional[CacheOptionsDictType] = None,
    ):
        if RSpaceFilesystem is None:
            raise self.required_package_exception
        config = context.config
        options = dict(cache_options or {})
        if config.mounts:
            options["mounts"] = tuple(m.strip() for m in config.mounts.split(",") if m.strip())
        if config.path_style:
            options["path_style"] = config.path_style
        return RSpaceFilesystem(
            config.endpoint,
            config.api_key,
            writable=bool(getattr(config, "writable", False)),
            fetch_sizes=config.fetch_sizes,
            **options,
        )

    def _to_filesystem_path(self, path: str, config=None) -> str:
        return "" if path in ("", "/") else path.lstrip("/")

    def _adapt_entry_path(self, filesystem_path: str, config=None) -> str:
        return "/" if not filesystem_path else "/" + filesystem_path.lstrip("/")


__all__ = ("RSpaceUnifiedFilesSource",)
