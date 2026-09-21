"""
Human-readable tree view of an RSpace filesystem.

Under the default path style a listing already reads as plain names. This helper is for
reading a whole subtree at once: it prints ``rspace.name`` and appends the global ID only
when two siblings share a name (or always / never, on request). It is also how you see the
names when the filesystem was opened with the ``labelled`` or ``id`` style.

    from rspace_client.fs import RSpaceFilesystem, print_tree
    print_tree(RSpaceFilesystem(url, key), "/gallery", max_depth=2)

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

from fs.base import FS
from fs.info import Info
from fs.path import basename, join

SHOW_IDS = ("collisions", "always", "never")


def label_for(info: Info, show_ids: str = "collisions", collision: bool = False) -> str:
    """Display label for an entry: the RSpace name, with its global ID when wanted."""
    rspace = info.raw.get("rspace") or {}
    name = rspace.get("name") or info.name
    if rspace.get("shortcut"):  # e.g. the 'sample:' folder inside a subsample
        name = f"{rspace['shortcut']}: {name}"
    gid = rspace.get("globalId")
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


def iter_tree(fs: FS, path: str = "/", max_depth: Optional[int] = None,
              show_ids: str = "collisions") -> Iterator[Tuple[int, Info, str, bool, List[bool]]]:
    """Yield (depth, info, label, is_last_sibling, ancestor_is_last_flags) in display order,
    one listing call per directory. The flags say, for each ancestor level, whether that
    ancestor was the last of its siblings, which is what draws the indent guides."""
    if show_ids not in SHOW_IDS:
        raise ValueError(f"show_ids must be one of {SHOW_IDS}")

    def walk(dir_path: str, depth: int, prefix_flags: List[bool]):
        entries = sorted(fs.scandir(dir_path, namespaces=["details"]),
                         key=lambda i: (not i.is_dir, ((i.raw.get("rspace") or {}).get("name") or i.name).lower()))
        names = Counter(((i.raw.get("rspace") or {}).get("name") or i.name) for i in entries)
        for index, info in enumerate(entries):
            last = index == len(entries) - 1
            name = (info.raw.get("rspace") or {}).get("name") or info.name
            yield depth, info, label_for(info, show_ids, names[name] > 1), last, prefix_flags
            if info.is_dir and (max_depth is None or depth + 1 < max_depth):
                yield from walk(join(dir_path, info.name), depth + 1, prefix_flags + [last])

    yield from walk(path, 0, [])


def format_tree(fs: FS, path: str = "/", max_depth: Optional[int] = None,
                show_ids: str = "collisions", sizes: bool = True) -> str:
    root_label = basename(path.rstrip("/")) or str(fs)
    lines = [root_label.rstrip("/") + "/"]
    for depth, info, label, last, flags in iter_tree(fs, path, max_depth, show_ids):
        stem = "".join("    " if done else "│   " for done in flags)
        branch = "└── " if last else "├── "
        suffix = "/" if info.is_dir else (f"  ({human_size(info.size)})" if sizes and info.size is not None else "")
        lines.append(f"{stem}{branch}{label}{suffix}")
    return "\n".join(lines)


def print_tree(fs: FS, path: str = "/", max_depth: Optional[int] = None,
               show_ids: str = "collisions", sizes: bool = True, file: TextIO = sys.stdout) -> None:
    print(format_tree(fs, path, max_depth, show_ids, sizes), file=file)
