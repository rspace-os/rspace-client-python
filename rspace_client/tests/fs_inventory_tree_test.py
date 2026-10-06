"""Inventory as a browsable tree (root, sections, pagination, records, attachment fields,
the sample shortcut) and its uploads, against the embedded mock server."""
import unittest
from io import BytesIO
from itertools import islice

from rspace_client.fs import GalleryFilesystem, InventoryFilesystem, RemoteApiError
from rspace_client.fs.inventory import Target
from rspace_client.fs.paths import last_segment
from .mock_server_case import MockServerTestCase


def names(fs, path):
    """The path segments of a directory's children, in listing order (fsspec's ``name`` is
    the full path)."""
    return [last_segment(n) for n in fs.ls(path, detail=False)]


class InventoryTreeTest(MockServerTestCase):

    def fs(self, **kw):
        return InventoryFilesystem(self.url, "k", **kw)

    def test_resolver(self):
        fs = self.fs()
        self.assertEqual("root", fs._resolve("").kind)
        self.assertEqual(Target("section", section="Samples"), fs._resolve("Samples"))
        t = fs._resolve("Containers/Freezer -80 [IC200]/Rack A [IC201]")
        self.assertEqual(("record", "IC201", "Containers"), (t.kind, t.gid, t.section))
        self.assertEqual("shortcut", fs._resolve("IC200/IC201/SS300/sample: x [SA1000]").kind)
        self.assertEqual("record", fs._resolve("Samples/Plasmid [SA1000]").kind)
        self.assertEqual(("attachment", "IF500"), (fs._resolve("IC200/IF500").kind, fs._resolve("IC200/IF500").gid))
        for bad in ("Nope", "IC200/IF500/x", "Containers/page-0", "GL1"):
            with self.assertRaises(FileNotFoundError, msg=bad):
                fs._resolve(bad)

    def test_root_and_sections(self):
        fs = self.fs()
        before = self.calls()
        self.assertEqual(["WB user1a", "Containers", "Samples", "Templates"], names(fs, ""))
        self.assertEqual(1, self.calls() - before)  # workbenches only; sections are virtual
        self.assertEqual("directory", fs.info("Containers")["type"])
        self.assertEqual(["Plasmid", "Bacterial strain"], names(fs, "Templates"))  # small: flat

    def test_sections_stream_without_exposing_pages(self):
        """A section simply contains its records; API paging is invisible (no page-N folders)."""
        fs = self.fs(page_size=5)
        listed = names(fs, "Containers")
        self.assertEqual(13, len(listed))  # 13 top-level containers, fetched 5 at a time
        self.assertFalse(any(n.startswith("page-") for n in listed))
        self.assertEqual(15, len(names(fs, "Samples")))
        before = self.calls()
        first_two = [last_segment(e["name"]) for e in islice(fs.scandir("Containers"), 2)]
        self.assertEqual(2, len(first_two))
        self.assertEqual(1, self.calls() - before)  # a slice costs one batch, not the whole section
        self.assertEqual(13, len(names(self.fs(page_size=50), "Containers")))  # one batch
        with self.assertRaises(FileNotFoundError):
            fs.ls("Containers/page-0")

    def test_container_children_and_drill_down(self):
        fs = self.fs()
        before = self.calls()
        rows = list(fs.scandir("Containers/Freezer -80 [IC200]"))
        self.assertEqual(1, self.calls() - before)
        self.assertEqual(["Rack A", "Rack B", "freezer_manual.pdf"], [last_segment(r["name"]) for r in rows])
        self.assertEqual(["directory", "directory", "file"], [r["type"] for r in rows])
        self.assertEqual(["Plasmid pUC19 #1", "Plasmid pUC19 #2"],
                         names(fs, "Freezer -80 [IC200]/Rack A [IC201]"))
        # by name too, from a parent the record is actually listed in; a segment carrying a
        # global ID resolves from anywhere, a bare name only where it appears
        self.assertEqual(["sample: Plasmid pUC19", "qc_gel.png"],  # folders first
                         names(fs, "Containers/Freezer -80/Rack A/Plasmid pUC19 #1"))
        with self.assertRaises(FileNotFoundError):
            fs.ls("Freezer -80")  # top-level containers live under Containers
        self.assertEqual(["Bench box", "Buffer stock #1", "Confocal microscope"],
                         names(fs, "WB user1a"))

    def test_bench_is_read_through_the_workbench_endpoint(self):
        # GET /containers/{id} answers 422 for a bench, on real servers and on the mock
        self.assertEqual(["Bench box", "Buffer stock #1", "Confocal microscope"],
                         names(self.fs(), "WB user1a [BE1]"))

    def test_instruments_on_a_bench_are_browsable(self):
        """Instruments (IN) sit on benches like subsamples and carry attachments."""
        fs = self.fs()
        self.assertIn("Confocal microscope", names(fs, "WB user1a [BE1]"))
        self.assertEqual(["calibration.pdf"], names(fs, "WB user1a/Confocal microscope"))
        self.assertEqual("directory", fs.info("IN2")["type"])
        out = BytesIO()
        fs.download_fileobj("IN2/calibration.pdf [IF504]", out)
        self.assertTrue(out.getvalue())

    def test_sample_shortcut_shows_attachments_only(self):
        fs = self.fs()
        shortcut = "IC200/IC201/SS300/sample: Plasmid pUC19 [SA1000]"
        self.assertEqual(["plasmid_map.gb"], names(fs, shortcut))  # no subsamples: no cycle
        info = fs.info(shortcut)
        self.assertEqual("directory", info["type"])
        self.assertEqual("sample", info["rspace"]["shortcut"])
        # the real sample folder still shows its subsamples
        self.assertEqual(["Plasmid pUC19 #1", "Plasmid pUC19 #2", "Safety Data", "plasmid_map.gb"],
                         names(fs, "Samples/Plasmid pUC19"))
        out = BytesIO()
        fs.download_fileobj(shortcut + "/plasmid_map.gb [IF501]", out)
        self.assertTrue(out.getvalue().startswith(b"LOCUS"))
        self.assertTrue(fs.cat_file(shortcut + "/plasmid_map.gb [IF501]").startswith(b"LOCUS"))

    def test_tree_helper_marks_shortcuts(self):
        from rspace_client.fs import format_tree
        text = format_tree(self.fs(), "WB user1a [BE1]")
        self.assertIn("sample: E. coli DH5a/", text)
        self.assertIn("sample: Buffer stock/", text)

    def test_attachment_fields_are_folders_holding_one_file(self):
        """A record carries files in two places: its own attachments, and attachment-type
        template fields, which hold at most one file each (like an ELN document field)."""
        fs = self.fs()
        sample = "Samples/Plasmid pUC19 [SA1000]"
        entries = names(fs, sample)
        self.assertIn("Safety Data", entries)               # attachment field -> folder
        self.assertIn("plasmid_map.gb", entries)            # the record's own attachment -> file
        self.assertNotIn("Concentration", entries)          # a number field cannot hold a file
        info = fs.info(f"{sample}/Safety Data")
        self.assertEqual("directory", info["type"])
        self.assertEqual("attachment", info["rspace"]["fieldType"])
        self.assertEqual(["msds.pdf"], names(fs, f"{sample}/Safety Data"))
        out = BytesIO()
        fs.download_fileobj(f"{sample}/Safety Data/msds.pdf", out)
        self.assertTrue(out.getvalue())
        # an empty attachment field is still visible, so a file can be put into it
        self.assertEqual([], names(fs, "Samples/E. coli DH5a/Datasheet"))

    def test_a_field_accepts_a_file_only_while_it_is_empty(self):
        """RSpace replaces the file in an attachment field; a folder does not suggest that,
        so an occupied field refuses the upload however the filesystem was opened."""
        empty = "Samples/E. coli DH5a/Datasheet"
        occupied = "Samples/Plasmid pUC19/Safety Data"
        fs = self.fs(writable=True, allow_delete=True)
        payload = BytesIO(b"sheet")
        payload.name = "sheet.pdf"
        fs.upload_fileobj(empty + "/sheet.pdf", payload)                     # empty field: accepted
        self.assertEqual(1, len(names(fs, empty)))
        for f in (self.fs(writable=True), fs):                # even with allow_delete
            with self.assertRaises(FileExistsError) as ctx:
                f.upload_fileobj(occupied + "/y.txt", BytesIO(b"y"))
            self.assertIn("msds.pdf", str(ctx.exception))
            self.assertIn("Remove the existing file first", str(ctx.exception))
        # the documented way round: clear it, then upload
        (current,) = names(fs, occupied)
        fs.rm_file(f"{occupied}/{current}")
        self.assertEqual([], names(fs, occupied))
        replacement = BytesIO(b"new")
        replacement.name = "new.pdf"
        fs.upload_fileobj(occupied + "/new.pdf", replacement)
        self.assertEqual(["new.pdf"], names(fs, occupied))

    def _media_gid(self, container, name):
        return next((e["rspace"].get("mediaFileGlobalId")
                     for e in self.fs().scandir(container) if last_segment(e["name"]) == name),
                    "no such entry")

    def test_an_attachment_becomes_a_gallery_item(self):
        """An Inventory file can exist only inside Inventory, invisible in the Gallery and
        reusable nowhere. Uploading through the Gallery and linking the result is what the
        web interface does, and it is what an ELN upload already did."""
        fs = self.fs(writable=True)
        for container in ("Samples/Plasmid pUC19",
                          "Samples/Plasmid pUC19/Plasmid pUC19 #1",
                          "Samples/E. coli DH5a/Datasheet"):
            attachment = fs.upload_fileobj(f"{container}/via-gallery.png", BytesIO(b"bytes"))
            self.assertEqual("via-gallery.png", attachment["name"])
            media = self._media_gid(container, "via-gallery.png")
            self.assertTrue(str(media).startswith("GL"),
                            f"{container} attachment should point at a Gallery file, got {media!r}")

    def test_the_inventory_only_upload_is_still_reachable(self):
        """The API offers both, and the deprecated class depends on the older one."""
        fs = self.fs(writable=True, via_gallery=False)
        fs.upload_fileobj("Samples/Plasmid pUC19/inventory-only.png", BytesIO(b"bytes"))
        self.assertIsNone(self._media_gid("Samples/Plasmid pUC19", "inventory-only.png"))

    def test_via_gallery_needs_an_eln_client_and_says_so(self):
        """It needs a second client. Left unset it turns itself on when one can be had;
        asking for it explicitly when one cannot is an error, not a silent downgrade to
        writing files that land somewhere other than the caller asked for."""
        from unittest.mock import MagicMock
        self.assertFalse(InventoryFilesystem(inv_client=MagicMock()).via_gallery)
        self.assertTrue(self.fs().via_gallery)  # built from a url and key
        with self.assertRaises(ValueError):
            InventoryFilesystem(inv_client=MagicMock(), via_gallery=True)

    def test_a_bench_or_template_is_refused_before_anything_is_uploaded(self):
        """Both present as ordinary record folders and the server refuses the attachment.
        If the Gallery upload ran first its file would be stranded, and the RSpace API
        cannot delete a Gallery file."""
        fs = self.fs(writable=True)
        gallery = GalleryFilesystem(self.url, "k")
        gallery_before = sum(len(files) for _, _, files in gallery.walk(""))
        for path, what in (("WB user1a/x.txt", "bench"), ("Templates/Plasmid/x.txt", "template")):
            with self.assertRaises(NotImplementedError, msg=what) as ctx:
                fs.upload_fileobj(path, BytesIO(b"x"))
            self.assertIn("does not accept attachments", str(ctx.exception))
        gallery.clear_name_cache()
        self.assertEqual(gallery_before, sum(len(files) for _, _, files in gallery.walk("")),
                         "nothing may reach the Gallery")

    def test_linking_an_existing_gallery_file_copies_no_bytes(self):
        fs = self.fs(writable=True)
        linked = fs.link("SA1000", "GL100")
        self.assertEqual("GL100", linked["mediaFileGlobalId"])
        self.assertIn(linked["name"], names(fs, "Samples/Plasmid pUC19"))

    def test_the_server_refuses_a_link_to_a_bench_or_template(self):
        fs = self.fs(writable=True)
        for gid in ("BE1", "IT1"):
            with self.assertRaises(RemoteApiError, msg=gid) as ctx:
                fs.link(gid, "GL100")
            self.assertIsInstance(ctx.exception, OSError)
            self.assertIsNotNone(ctx.exception.api_error)
            self.assertIn(ctx.exception.status, (400, 409, 422))

    def test_whole_tree_walk_terminates(self):
        fs = self.fs(page_size=50)
        dirs = [p for p, _, _ in fs.walk("")]
        self.assertEqual(len(dirs), len(set(dirs)))
        self.assertIn("WB user1a/Bench box/E. coli DH5a #2/sample: E. coli DH5a", dirs)
        self.assertTrue(len(dirs) > 40)
        # find(withdirs=True) walks the same tree and reports the same directories
        found = fs.find("WB user1a", withdirs=True)
        self.assertIn("WB user1a/Bench box/E. coli DH5a #2/sample: E. coli DH5a", found)

    def test_writes(self):
        fs = self.fs(writable=True, allow_delete=True)
        payload = BytesIO(b"x")
        payload.name = "qc.txt"
        fs.upload_fileobj("Containers/Freezer -80/Rack A/Plasmid pUC19 #1/qc.txt", payload)
        self.assertIn("qc.txt", names(fs, "IC201/SS300"))
        fs.upload_fileobj("IC201/SS300/sample: Plasmid pUC19/extra.txt", BytesIO(b"y"))  # attaches to the sample
        self.assertEqual(2, len([e for e in fs.scandir("SA1000") if e["type"] != "directory"]))
        with self.assertRaises(NotImplementedError):
            fs.upload_fileobj("Containers/z.txt", BytesIO(b"z"))
        with self.assertRaises(NotImplementedError):
            fs.mkdir("Containers/new")


if __name__ == "__main__":
    unittest.main()
