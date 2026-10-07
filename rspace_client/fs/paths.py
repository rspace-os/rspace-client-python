"""
Path grammar helpers shared by the RSpace filesystems.

A path is a slash-delimited sequence of segments. Below a filesystem root each
segment addresses an RSpace record, and there are three ways of writing one:

    name        ``microscope.png``            the record's own name
    labelled    ``microscope.png [GL100]``    name and global ID
    id          ``GL100``                     the bare global ID

The *path style* decides which of these a listing produces. A segment carrying a global
ID is accepted under every style, so a path copied from a labelled or id listing resolves
anywhere; a bare name only resolves under the ``name`` style, where the lookup exists.
A segment carrying a global ID resolves in one call and survives a rename. A bare
name has to be looked up among its parent's children, and where a folder holds two
records with the same name the listing appends the global ID to the second and
later ones, so every segment in a listing stays unique and addressable.

Each filesystem adds its own vocabulary on top of this (the Inventory sections, for
instance); what lives here is only what all of them share.
"""
from __future__ import annotations

import re
from typing import Optional, Tuple

from posixpath import basename

GLOBAL_ID = re.compile(r"^[A-Z]{2}\d+$")
LABELLED = re.compile(r"^(?P<label>.*) \[(?P<gid>[A-Z]{2}\d+)\]$", re.S)
#: 'data [GL112].csv': the same thing with the extension moved back to the end, so that a
#: disambiguated file name still tells a consumer what kind of file it is.
LABELLED_EXT = re.compile(r"^(?P<stem>.*) \[(?P<gid>[A-Z]{2}\d+)\](?P<ext>\.[A-Za-z0-9]{1,8})$", re.S)
EXTENSION = re.compile(r"^(?P<stem>.+)(?P<ext>\.[A-Za-z0-9]{1,8})$")

ROOT_PATHS = ("", "/", ".", "./")
PATH_STYLES = ("name", "labelled", "id")


def is_root(path: str) -> bool:
    return path in ROOT_PATHS


def segments(path: str) -> list:
    """The path's segments, without empty ones ('/a//b/' -> ['a', 'b'])."""
    return [s for s in path.split("/") if s]


def last_segment(path: str) -> str:
    """The final path segment ('' for the root)."""
    return basename(path.rstrip("/")) if not is_root(path) else ""


def parse_segment(segment: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Split a segment into (global_id, label).
    ``'GF12'`` -> ('GF12', None); ``'Images [GF12]'`` -> ('GF12', 'Images');
    ``'New folder'`` -> (None, 'New folder').
    """
    segment = segment or ""
    if GLOBAL_ID.match(segment):
        return segment, None
    match = LABELLED.match(segment)
    if match:
        return match.group("gid"), match.group("label")
    match = LABELLED_EXT.match(segment)
    if match:
        return match.group("gid"), match.group("stem") + match.group("ext")
    return None, segment


#: Segments a path reserves for itself. A record named '.' or '..' is addressed by its
#: global ID instead, since those two can never mean a child of the current directory.
RESERVED_SEGMENTS = (".", "..")


def _sanitise_label(name) -> str:
    """Make an RSpace name safe as a path segment.

    RSpace names are written by people and can hold anything. Both separators are replaced
    (backslash as well as slash, because the segment may end up as a file name on Windows),
    NULs are dropped and whitespace is collapsed. A name that reduces to ``.`` or ``..``
    returns ``''``, which makes ``segment_for`` fall back to the record's global ID: those
    two segments address a directory rather than a child, so no path could reach the record.
    """
    text = str(name or "").replace("/", "-").replace("\\", "-").replace("\0", "")
    text = re.sub(r"\s+", " ", text).strip()
    return "" if text in RESERVED_SEGMENTS else text


def _labelled_segment(name, gid: str) -> str:
    """'Images [GF12]' (falls back to the bare id when the name is empty)."""
    label = _sanitise_label(name)
    return f"{label} [{gid}]" if label else gid


def disambiguated_segment(name, gid: str) -> str:
    """A unique segment for a record whose name a sibling already took.

    ``'data.csv'`` becomes ``'data [GL112].csv'`` rather than ``'data.csv [GL112]'``, so
    that the file still ends in ``.csv`` when it is downloaded or handed to a tool that
    picks its type from the extension.
    """
    label = _sanitise_label(name)
    if not label:
        return gid
    match = EXTENSION.match(label)
    if match:
        return f"{match.group('stem')} [{gid}]{match.group('ext')}"
    return f"{label} [{gid}]"


#: Appended to a segment whose record cannot be written to, under the ``name`` style only.
#: Parentheses rather than brackets, because brackets already mean a global ID here and in
#: ``disambiguated_segment``; reusing them would make a segment ambiguous to read and to parse.
#: The word is "signed" rather than "read-only" because `signed` is the only lock the API
#: reports: a document shared read-only with you is also unwritable and looks identical.
READ_ONLY_MARKER = " (signed)"


def mark_read_only(segment: str) -> str:
    """``'Results'`` -> ``'Results (signed)'``. Idempotent."""
    return segment if segment.endswith(READ_ONLY_MARKER) else segment + READ_ONLY_MARKER


def unmarked(segment: str) -> str:
    """The segment without its read-only marker, so a path stored before a document was
    signed still resolves afterwards."""
    return segment[:-len(READ_ONLY_MARKER)] if segment.endswith(READ_ONLY_MARKER) else segment


def segment_for(style: str, name, gid: str) -> str:
    """The path segment for a record under the given path style."""
    if style == "id":
        return gid
    if style == "labelled":
        return _labelled_segment(name, gid)
    label = _sanitise_label(name) or gid  # "name": the bare name, falling back to the id
    # A name that would itself parse as an address ('GL9', 'report [GL111].csv') must not be
    # listed as one: it would resolve to that other record. Give it its real id, the way a
    # colliding sibling gets one, so the listed segment says what it addresses.
    return disambiguated_segment(name, gid) if parse_segment(label)[0] is not None else label
