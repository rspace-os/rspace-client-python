"""
The ``name`` path style: segments are the records' own names.

Names, not labelled ``Name [GID]`` segments, are the default because fsspec consumers such
as Galaxy derive both the label they display and the path they address from an entry's
``name``, and a label with the ID appended would travel into downloaded file names and
swallow the extension (``microscope.png [GL100]`` has no usable extension, and Galaxy picks
a dataset's type from one).

Under the ``name`` style a segment is just the name, a segment carrying a global ID is
still accepted, and a name is resolved against its parent's listing.
"""
import mimetypes
import os
import tempfile
import unittest
from unittest.mock import MagicMock

from rspace_client.fs import GalleryFilesystem, InventoryFilesystem, RSpaceFilesystem, paths
from .mock_server_case import MockServerTestCase, segments




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
        self.assertEqual(["gallery/Images", "gallery/Documents", "gallery/Chemistry", "gallery/Api Imports"],
                         rfs.ls("gallery", detail=False))
        self.assertIn("gallery/Images/microscope.png", rfs.ls("gallery/Images", detail=False))
        self.assertIn("inventory/Containers", rfs.ls("inventory", detail=False))
        self.assertIn("workspace/Project Alpha/Alpha protocol/Results",
                      rfs.ls("workspace/Project Alpha/Alpha protocol", detail=False))
        # a signed document's fields carry the read-only marker under this style, and the
        # unmarked spelling still resolves
        signed = rfs.ls("workspace/Project Alpha/Signed protocol", detail=False)
        self.assertEqual(["Data (signed)"], segments(signed))
        self.assertFalse(rfs.info("workspace/Project Alpha/Signed protocol/Data")["writable"])

    def test_siblings_sharing_a_name_stay_addressable(self):
        rfs = self.fs()
        entries = segments(rfs.ls("gallery/Documents", detail=False))  # two files called data.csv
        self.assertEqual(len(entries), len(set(entries)))
        self.assertIn("data.csv", entries)
        self.assertIn("data [GL112].csv", entries)

    def test_a_record_resolves_under_every_spelling(self):
        rfs = self.fs()
        for segment in ("data [GL112].csv", "data.csv [GL112]", "GL112"):
            entry = rfs.info("gallery/Documents/" + segment)
            self.assertEqual("GL112", entry["rspace"]["globalId"], segment)
            self.assertEqual("gallery/Documents/" + segment, entry["name"], segment)
        self.assertEqual("GL111", rfs.info("gallery/Documents/data.csv")["rspace"]["globalId"])

    def test_a_name_that_is_not_there_is_not_found(self):
        rfs = self.fs()
        with self.assertRaises(FileNotFoundError):
            rfs.info("gallery/Images/nothing-like-this.png")
        self.assertFalse(rfs.exists("gallery/Images/nothing-like-this.png"))

    def test_downloaded_files_keep_a_usable_extension(self):
        rfs = self.fs()
        out = tempfile.mkdtemp()
        rfs.get("gallery/Documents/", out + "/", recursive=True)
        for name in os.listdir(out):
            self.assertIsNotNone(mimetypes.guess_type(name)[0], name)
        self.assertEqual({"data.csv", "data [GL112].csv", "protocol.docx"}, set(os.listdir(out)))

    def test_a_folder_can_be_created_and_then_copied_into_by_name(self):
        """Under the labelled style the new folder's real segment carried an ID the caller
        had no way to know, so copying into what it had just created failed."""
        rfs = self.fs(writable=True)
        rfs.mkdir("gallery/Documents/Round trip")
        source = tempfile.mkdtemp()
        with open(os.path.join(source, "notes.txt"), "wb") as handle:
            handle.write(b"hello")
        rfs.put(source + "/", "gallery/Documents/Round trip/", recursive=True)
        self.assertEqual(["gallery/Documents/Round trip/notes.txt"],
                         rfs.ls("gallery/Documents/Round trip", detail=False))
        self.assertEqual(b"hello", rfs.cat_file("gallery/Documents/Round trip/notes.txt"))

    def test_resolving_a_name_is_remembered(self):
        gallery = GalleryFilesystem(self.url, "k", path_style="name", fetch_sizes=False)
        gallery.ls("Images/2026-09 run")
        before = self.calls()
        gallery.ls("Images/2026-09 run")
        self.assertEqual(1, self.calls() - before)  # the listing itself; the parents are cached
        before = self.calls()
        gallery.info("Images/2026-09 run")
        self.assertEqual(1, self.calls() - before)  # the folder record; the lookup costs nothing

    def test_fetching_sizes_costs_one_call_per_file(self):
        """The folder-tree listing carries no size; by default every file is fetched for it."""
        plain = GalleryFilesystem(self.url, "k", path_style="name", fetch_sizes=False)
        plain.ls("Images/2026-09 run")  # resolve the parents first
        before = self.calls()
        entries = plain.ls("Images/2026-09 run")
        self.assertEqual(1, self.calls() - before)
        self.assertEqual([None], [e["size"] for e in entries])

        sized = GalleryFilesystem(self.url, "k", path_style="name")
        sized.ls("Images/2026-09 run")
        before = self.calls()
        entries = sized.ls("Images/2026-09 run")
        self.assertEqual(1 + len(entries), self.calls() - before)
        self.assertTrue(all(isinstance(e["size"], int) for e in entries))

    def test_a_change_forgets_what_was_resolved(self):
        gallery = GalleryFilesystem(self.url, "k", path_style="name", writable=True)
        gallery.ls("Documents")
        self.assertTrue(gallery._name_cache)
        gallery.mkdir("Documents/New folder")
        self.assertFalse(gallery._name_cache)

    def test_a_name_that_looks_like_an_address_is_listed_with_its_real_id(self):
        """Review F4: a record named 'GL9' or 'report [GL111].csv' would otherwise be listed
        under a segment that resolves to the *other* record."""
        self.assertEqual("GL9 [GL6]", paths.segment_for("name", "GL9", "GL6"))
        self.assertEqual("report [GL111] [GL5].csv", paths.segment_for("name", "report [GL111].csv", "GL5"))
        self.assertEqual("notes [draft]", paths.segment_for("name", "notes [draft]", "GL7"))  # not an address
        for listed, gid in (("GL9 [GL6]", "GL6"), ("report [GL111] [GL5].csv", "GL5")):
            self.assertEqual(gid, paths.parse_segment(listed)[0])

        files = [{"id": 5, "globalId": "GL5", "name": "report [GL111].csv"},
                 {"id": 6, "globalId": "GL6", "name": "GL9"},
                 {"id": 111, "globalId": "GL111", "name": "other.csv"},
                 {"id": 9, "globalId": "GL9", "name": "nine.csv"}]
        client = MagicMock()
        client.list_folder_tree.side_effect = lambda folder_id=None, typesToInclude=[], **kw: (
            {"records": [{"id": 2, "globalId": "FL2", "name": "Gallery"}]} if folder_id is None
            else {"records": files})
        client.get_file_info.side_effect = lambda fid: next(f for f in files if str(f["id"]) == str(fid))
        fs = GalleryFilesystem(eln_client=client)
        self.assertEqual(["report [GL111] [GL5].csv", "GL9 [GL6]", "other.csv", "nine.csv"], fs.ls("", detail=False))
        for listed in fs.ls("", detail=False):
            entry = fs.info(listed)
            self.assertEqual(listed, entry["name"])
            # every listed name opens the record it shows
            self.assertEqual(paths.parse_segment(listed)[0] or entry["globalId"], entry["globalId"])
            self.assertEqual(next(f["name"] for f in files if f["globalId"] == entry["globalId"]),
                             entry["rspace"]["name"])

    def test_a_hostile_record_name_stays_addressable(self):
        """A name is chosen by an RSpace user, so on a shared instance it crosses a trust
        boundary. One that would break the path grammar is listed by its global ID."""
        client = MagicMock()
        hostile = {"id": 5, "globalId": "IF5", "name": ".."}
        client.get_container_by_id.return_value = {
            "id": 1, "globalId": "IC1", "name": "Box", "locations": [],
            "attachments": [hostile, {"id": 6, "globalId": "IF6", "name": "a/b.txt"}]}
        client.get_attachment_by_id.return_value = hostile
        fs = InventoryFilesystem(inv_client=client)
        self.assertEqual(["IC1/IF5", "IC1/a-b.txt"], fs.ls("IC1", detail=False))
        self.assertEqual("IC1/IF5", fs.info("IC1/IF5")["name"])
        self.assertEqual("..", fs.info("IC1/IF5")["rspace"]["name"])  # the real name is kept

    def test_a_filesystem_that_can_delete_does_not_claim_to_be_read_only(self):
        """writable and allow_delete are deliberately separate, so a filesystem can
        delete while refusing uploads. Reporting that as read-only would be a lie."""
        for kw, read_only in (({}, True),
                              ({"writable": True}, False),
                              ({"allow_delete": True}, False),
                              ({"writable": True, "allow_delete": True}, False)):
            self.assertEqual(read_only, self.fs(**kw).read_only, kw)
            self.assertEqual(read_only, GalleryFilesystem(self.url, "k", **kw).read_only, kw)

    def test_the_other_styles_still_work(self):
        self.assertIn("gallery/Images [GF10]", self.fs(path_style="labelled").ls("gallery", detail=False))
        self.assertIn("gallery/GF10", self.fs(path_style="id").ls("gallery", detail=False))
        with self.assertRaises(ValueError):
            self.fs(path_style="nonsense")

    def test_glob_finds_a_bracketed_segment_in_listing_order(self):
        """Galaxy's search escapes '[' as '\\[' and hands the pattern to glob; fsspec's own glob
        would read '[GL112]' as a character class and find nothing."""
        rfs = self.fs()
        self.assertEqual(["gallery/Documents/data [GL112].csv"], rfs.glob("gallery/Documents/*\\[GL112\\]*"))
        listed = [n for n in rfs.ls("gallery/Documents", detail=False) if "data" in paths.last_segment(n)]
        self.assertEqual(listed, rfs.glob("gallery/Documents/*data*"))  # listing order, not sorted
        self.assertEqual(["gallery/Documents/data.csv", "gallery/Documents/data [GL112].csv"], listed)
        gallery = GalleryFilesystem(self.url, "k", path_style="name")
        self.assertEqual(["Documents/data [GL112].csv"], gallery.glob("Documents/*\\[GL112\\]*"))
        found = gallery.glob("Documents/*CSV*", detail=True)  # case-insensitive, entries carried
        self.assertEqual(["GL111", "GL112"], [e["globalId"] for e in found.values()])


if __name__ == "__main__":
    unittest.main()
