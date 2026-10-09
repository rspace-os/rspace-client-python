"""
Human-readable tree view of an RSpace filesystem.

Under the default path style a listing already reads as plain names. This helper is for
reading a whole subtree at once: it prints the RSpace name and appends the global ID only
when two siblings share a name (or always / never, on request). It is also how you see the
names when the filesystem was opened with the ``labelled`` or ``id`` style.

    from rspace_client.fs import RSpaceFilesystem, print_tree
    print_tree(RSpaceFilesystem(url, key), "gallery", max_depth=2)

    gallery/
    ├── Images
    │   ├── microscope.png  (1.1 kB)
    │   └── gel.jpg  (868 B)
    └── Documents
        ├── data.csv (GL111)  (27 B)
        └── data.csv (GL112)  (27 B)
"""
from __future__ import annotations

import sys
from collections import Counter
from typing import Iterator, List, Optional, TextIO, Tuple

from fsspec.spec import AbstractFileSystem

from . import paths

SHOW_IDS = ("collisions", "always", "never")


def _display_name(entry: dict) -> str:
    rspace = entry.get("rspace") or {}
    return rspace.get("name") or paths.last_segment(entry["name"])


def label_for(entry: dict, show_ids: str = "collisions", collision: bool = False) -> str:
    """Display label for an entry: the RSpace name, with its global ID when wanted."""
    rspace = entry.get("rspace") or {}
    name = _display_name(entry)
    if rspace.get("shortcut"):  # e.g. the 'sample:' folder inside a subsample
        name = f"{rspace['shortcut']}: {name}"
    gid = entry.get("globalId")
    if gid and (show_ids == "always" or (show_ids == "collisions" and collision)):
        return f"{name} ({gid})"
    return name


def human_size(size: Optional[int]) -> str:
    if size is None:
        return ""
    value = float(size)
    for unit in ("B", "kB", "MB", "GB"):
        if value < 1000:
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1000.0
    return f"{value:.1f} TB"


def iter_tree(fs: AbstractFileSystem, path: str = "", max_depth: Optional[int] = None,
              show_ids: str = "collisions") -> Iterator[Tuple[int, dict, str, bool, List[bool]]]:
    """Yield (depth, entry, label, is_last_sibling, ancestor_is_last_flags) in display order,
    one listing call per directory. The flags say, for each ancestor level, whether that
    ancestor was the last of its siblings, which is what draws the indent guides."""
    if show_ids not in SHOW_IDS:
        raise ValueError(f"show_ids must be one of {SHOW_IDS}")

    def walk(dir_path: str, depth: int, prefix_flags: List[bool]):
        entries = sorted(fs.ls(dir_path, detail=True),
                         key=lambda e: (e["type"] != "directory", _display_name(e).lower()))
        names = Counter(_display_name(e) for e in entries)
        for index, entry in enumerate(entries):
            last = index == len(entries) - 1
            yield depth, entry, label_for(entry, show_ids, names[_display_name(entry)] > 1), last, prefix_flags
            if entry["type"] == "directory" and (max_depth is None or depth + 1 < max_depth):
                yield from walk(entry["name"], depth + 1, prefix_flags + [last])

    yield from walk(fs._strip_protocol(path), 0, [])


def format_tree(fs: AbstractFileSystem, path: str = "", max_depth: Optional[int] = None,
                show_ids: str = "collisions", sizes: bool = True) -> str:
    root_label = paths.last_segment(path) or str(getattr(fs, "server", None) or type(fs).__name__)
    lines = [root_label.rstrip("/") + "/"]
    for depth, entry, label, last, flags in iter_tree(fs, path, max_depth, show_ids):
        stem = "".join("    " if done else "│   " for done in flags)
        branch = "└── " if last else "├── "
        size = entry.get("size")
        suffix = "/" if entry["type"] == "directory" else (f"  ({human_size(size)})" if sizes and size is not None else "")
        lines.append(f"{stem}{branch}{label}{suffix}")
    return "\n".join(lines)


def print_tree(fs: AbstractFileSystem, path: str = "", max_depth: Optional[int] = None,
               show_ids: str = "collisions", sizes: bool = True, file: TextIO = sys.stdout) -> None:
    print(format_tree(fs, path, max_depth, show_ids, sizes), file=file)
