"""
The ``name`` path style: segments are the records' own names.

Names, not labelled ``Name [GID]`` segments, are the default because PyFilesystem builds
every path by joining ``info.name`` onto its parent, and consumers such as Galaxy derive
both the label they display and the path they address from that one field. A label with
the ID appended would travel into downloaded file names and swallow the extension
(``microscope.png [GL100]`` has no usable extension, and Galaxy picks a dataset's type
from one).

Under the ``name`` style a segment is just the name, a segment carrying a global ID is
still accepted, and a name is resolved against its parent's listing.
"""
import mimetypes
import os
import tempfile
import unittest

import fs as pyfs
import fs.copy
from fs import errors

from rspace_client.fs import RSpaceFilesystem, GalleryFilesystem, paths
from .mock_server_case import MockServerTestCase


class SegmentGrammarTest(unittest.TestCase):

    def test_a_disambiguated_name_keeps_its_extension(self):
        self.assertEqual("data [GL112].csv", paths.disambiguated_segment("data.csv", "GL112"))
        self.assertEqual("notes [GL112]", paths.disambiguated_segment("notes", "GL112"))
        self.assertEqual("GL112", paths.disambiguated_segment("", "GL112"))

    def test_every_spelling_of_a_segment_parses_back_to_the_same_record(self):
        for segment in ("GL112", "data.csv [GL112]", "data [GL112].csv"):
            self.assertEqual("GL112", paths.parse_segment(segment)[0], segment)
        self.assertEqual("data.csv", paths.parse_segment("data [GL112].csv")[1])
        self.assertEqual((None, "data.csv"), paths.parse_segment("data.csv"))

    def test_a_name_is_never_mistaken_for_a_labelled_segment(self):
        self.assertEqual((None, "notes [draft]"), paths.parse_segment("notes [draft]"))
        self.assertEqual((None, "report [v2].pdf"), paths.parse_segment("report [v2].pdf"))

    def test_a_name_reserved_by_the_path_grammar_falls_back_to_the_global_id(self):
        """'.' and '..' address a directory rather than a child, so a record named either
        would be unreachable (and would send a walk round in circles). Use its ID instead."""
        for name in (".", "..", " .. ", "\t..\n"):
            self.assertEqual("GL1", paths.segment_for("name", name, "GL1"), name)
            self.assertEqual("GL1", paths.segment_for("labelled", name, "GL1"), name)
            self.assertEqual("GL1", paths.disambiguated_segment(name, "GL1"), name)
        # anything else that merely contains dots is an ordinary name
        for name, segment in (("...", "..."), (".hidden", ".hidden"), ("./", ".-"), ("../x", "..-x")):
            self.assertEqual(segment, paths.segment_for("name", name, "GL1"), name)

    def test_labelled_duplicate_names_stay_distinct(self):
        a, b = paths.segment_for("labelled", "data.csv", "GL111"), paths.segment_for("labelled", "data.csv", "GL112")
        self.assertNotEqual(a, b)
        self.assertEqual(("GL111", "data.csv"), paths.parse_segment(a))

    def test_labels_are_sanitised_and_brackets_in_names_survive(self):
        self.assertEqual("A-B C [GF1]", paths.segment_for("labelled", "A/B   C", "GF1"))
        seg = paths.segment_for("labelled", "Run [rep 2]", "SD9")
        self.assertEqual("Run [rep 2] [SD9]", seg)
        self.assertEqual(("SD9", "Run [rep 2]"), paths.parse_segment(seg))
        self.assertEqual("GF1", paths.segment_for("labelled", "", "GF1"))
        self.assertEqual((None, "New folder"), paths.parse_segment("New folder"))

    def test_both_separators_are_replaced(self):
        """A backslash is a separator on Windows, so it cannot survive into a segment that a
        consumer may write to disk."""
        self.assertEqual("a-b", paths.segment_for("name", "a/b", "GL1"))
        self.assertEqual("a-b", paths.segment_for("name", "a\\b", "GL1"))
        self.assertEqual("C:-Users-x.png", paths.segment_for("name", "C:\\Users\\x.png", "GL1"))
        self.assertNotIn("\0", paths.segment_for("name", "a\0b", "GL1"))


class NamePathStyleTest(MockServerTestCase):

    def fs(self, **kw):
        kw.setdefault("path_style", "name")
        return RSpaceFilesystem(self.url, "k", **kw)

    def test_listings_show_plain_names(self):
        rfs = self.fs()
        self.assertEqual(["Images", "Documents", "Chemistry", "Api Imports"], rfs.listdir("/gallery"))
        self.assertIn("microscope.png", rfs.listdir("/gallery/Images"))
        self.assertIn("Containers", rfs.listdir("/inventory"))
        self.assertIn("Results", rfs.listdir("/workspace/Project Alpha/Alpha protocol"))

    def test_siblings_sharing_a_name_stay_addressable(self):
        rfs = self.fs()
        entries = rfs.listdir("/gallery/Documents")  # the fixtures hold two files called data.csv
        self.assertEqual(len(entries), len(set(entries)))
        self.assertIn("data.csv", entries)
        self.assertIn("data [GL112].csv", entries)

    def test_a_record_resolves_under_every_spelling(self):
        rfs = self.fs()
        for segment in ("data [GL112].csv", "data.csv [GL112]", "GL112"):
            info = rfs.getinfo("/gallery/Documents/" + segment)
            self.assertEqual("GL112", info.raw["rspace"]["globalId"], segment)
        self.assertEqual("GL111", rfs.getinfo("/gallery/Documents/data.csv").raw["rspace"]["globalId"])

    def test_a_name_that_is_not_there_is_not_found(self):
        rfs = self.fs()
        with self.assertRaises(errors.ResourceNotFound):
            rfs.getinfo("/gallery/Images/nothing-like-this.png")

    def test_downloaded_files_keep_a_usable_extension(self):
        rfs = self.fs()
        out = tempfile.mkdtemp()
        pyfs.copy.copy_dir(rfs, "/gallery/Documents", pyfs.open_fs(out), "/")
        for name in os.listdir(out):
            self.assertIsNotNone(mimetypes.guess_type(name)[0], name)
        self.assertEqual({"data.csv", "data [GL112].csv", "protocol.docx"}, set(os.listdir(out)))

    def test_a_folder_can_be_created_and_then_copied_into_by_name(self):
        """Under the labelled style the new folder's real segment carried an ID the caller
        had no way to know, so copying into what it had just created failed."""
        rfs = self.fs(writable=True)
        rfs.makedir("/gallery/Documents/Round trip")
        source = pyfs.open_fs("mem://")
        source.writebytes("/notes.txt", b"hello")
        pyfs.copy.copy_dir(source, "/", rfs, "/gallery/Documents/Round trip")
        self.assertEqual(["notes.txt"], rfs.listdir("/gallery/Documents/Round trip"))

    def test_resolving_a_name_is_remembered(self):
        gallery = GalleryFilesystem(self.url, "k", path_style="name")
        gallery.listdir("/Images/2026-09 run")
        before = self.calls()
        gallery.listdir("/Images/2026-09 run")
        self.assertEqual(1, self.calls() - before)  # the listing itself; the parents are cached

    def test_a_change_forgets_what_was_resolved(self):
        gallery = GalleryFilesystem(self.url, "k", path_style="name", writable=True)
        gallery.listdir("/Documents")
        self.assertTrue(gallery._name_cache)
        gallery.makedir("/Documents/New folder")
        self.assertFalse(gallery._name_cache)

    def test_a_name_that_looks_like_an_address_is_listed_with_its_real_id(self):
        """Review F4: a record named 'GL9' or 'report [GL111].csv' would otherwise be listed
        under a segment that resolves to the *other* record."""
        self.assertEqual("GL9 [GL6]", paths.segment_for("name", "GL9", "GL6"))
        self.assertEqual("report [GL111] [GL5].csv", paths.segment_for("name", "report [GL111].csv", "GL5"))
        self.assertEqual("notes [draft]", paths.segment_for("name", "notes [draft]", "GL7"))  # not an address
        for listed, gid in (("GL9 [GL6]", "GL6"), ("report [GL111] [GL5].csv", "GL5")):
            self.assertEqual(gid, paths.parse_segment(listed)[0])

        from unittest.mock import MagicMock
        from rspace_client.fs import GalleryFilesystem
        files = [{"id": 5, "globalId": "GL5", "name": "report [GL111].csv"},
                 {"id": 6, "globalId": "GL6", "name": "GL9"},
                 {"id": 111, "globalId": "GL111", "name": "other.csv"},
                 {"id": 9, "globalId": "GL9", "name": "nine.csv"}]
        client = MagicMock()
        client.list_folder_tree.side_effect = lambda folder_id=None, typesToInclude=[], **kw: (
            {"records": [{"id": 2, "globalId": "FL2", "name": "Gallery"}]} if folder_id is None
            else {"records": files})
        client.link_exists.return_value = False
        client.get_file_info.side_effect = lambda fid: next(f for f in files if str(f["id"]) == str(fid))
        fs = GalleryFilesystem(eln_client=client)
        self.assertEqual(["report [GL111] [GL5].csv", "GL9 [GL6]", "other.csv", "nine.csv"], fs.listdir("/"))
        for listed in fs.listdir("/"):
            info = fs.getinfo("/" + listed)
            self.assertEqual(listed, info.name)  # every listed name opens the record it shows

    def test_a_hostile_record_name_stays_addressable(self):
        """A name is chosen by an RSpace user, so on a shared instance it crosses a trust
        boundary. One that would break the path grammar is listed by its global ID."""
        from unittest.mock import MagicMock
        from rspace_client.fs import InventoryFilesystem
        client = MagicMock()
        hostile = {"id": 5, "globalId": "IF5", "name": ".."}
        client.get_container_by_id.return_value = {
            "id": 1, "globalId": "IC1", "name": "Box", "locations": [],
            "attachments": [hostile, {"id": 6, "globalId": "IF6", "name": "a/b.txt"}]}
        client.get_attachment_by_id.return_value = hostile
        fs = InventoryFilesystem(inv_client=client)
        self.assertEqual(["IF5", "a-b.txt"], fs.listdir("/IC1"))
        self.assertEqual("IF5", fs.getinfo("/IC1/IF5").name)
        self.assertEqual("..", fs.getinfo("/IC1/IF5").raw["rspace"]["name"])  # the real name is kept

    def test_a_filesystem_that_can_delete_does_not_claim_to_be_read_only(self):
        """writable and allow_delete are deliberately separate, so a filesystem can
        delete while refusing uploads. Reporting that as read-only would be a lie."""
        for kw, read_only in (({}, True),
                              ({"writable": True}, False),
                              ({"allow_delete": True}, False),
                              ({"writable": True, "allow_delete": True}, False)):
            self.assertEqual(read_only, self.fs(**kw).getmeta()["read_only"], kw)
            self.assertEqual(read_only, GalleryFilesystem(self.url, "k", **kw).getmeta()["read_only"], kw)

    def test_the_other_styles_still_work(self):
        self.assertIn("Images [GF10]", self.fs(path_style="labelled").listdir("/gallery"))
        self.assertIn("GF10", self.fs(path_style="id").listdir("/gallery"))
        with self.assertRaises(ValueError):
            self.fs(path_style="nonsense")


if __name__ == "__main__":
    unittest.main()
