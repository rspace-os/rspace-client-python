"""The unified RSpaceFilesystem mount, its copy/link semantics, the tree helper and the
rspace:// opener, exercised offline against the embedded mock server."""
import os
import unittest
from io import BytesIO
from unittest.mock import patch

import fs as pyfs
import fs.copy
from fs import errors
from fs.opener.errors import OpenerError

from rspace_client.fs import GalleryFilesystem, RSpaceFilesystem, format_tree
from .mock_server_case import MockServerTestCase


class RSpaceFilesystemTest(MockServerTestCase):

    def test_root_lists_the_worlds_and_shares_clients(self):
        rs = RSpaceFilesystem(self.url, "k")
        self.assertEqual(["gallery", "inventory", "workspace"], rs.listdir("/"))
        self.assertTrue(rs.getinfo("/gallery").is_dir)
        self.assertIs(rs.gallery.eln_client, rs.eln_client)
        self.assertIs(rs.inventory.inv_client, rs.inv_client)
        self.assertTrue(rs.getmeta()["read_only"])

    def test_a_missing_record_behind_a_global_id_does_not_exist(self):
        # a server 404 must be a PyFilesystem ResourceNotFound, so exists() is False
        rs = RSpaceFilesystem(self.url, "k")
        for path in ("/gallery/GF99999", "/gallery/GL99999", "/inventory/IC99999",
                     "/inventory/Samples/SA99999", "/workspace/SD99999", "/workspace/FL99999"):
            self.assertFalse(rs.exists(path), path)
            with self.assertRaises(errors.ResourceNotFound, msg=path):
                rs.getinfo(path)
        self.assertFalse(rs.exists("/gallery/GF99999/anything"))

    def test_browse_through_the_mount(self):
        rs = RSpaceFilesystem(self.url, "k")
        self.assertEqual(["Images", "Documents", "Chemistry", "Api Imports"], rs.listdir("/gallery"))
        rows = list(rs.filterdir("/gallery/Documents", namespaces=["details"]))
        # two files are called data.csv; the second carries its id, and keeps its extension
        self.assertEqual(["protocol.docx", "data.csv", "data [GL112].csv"], [r.name for r in rows])
        self.assertEqual(["Rack A", "Rack B", "freezer_manual.pdf"], rs.listdir("/inventory/IC200"))
        walked = {p for p, _, _ in rs.walk("/", namespaces=["details"])}
        self.assertIn("/gallery/Images/2026-09 run", walked)
        self.assertIn("/inventory", walked)  # walking the whole mount works
        self.assertIn("/inventory/WB user1a/Bench box", walked)
        self.assertEqual(["WB user1a", "Containers", "Samples", "Templates"], rs.listdir("/inventory"))
        out = BytesIO()
        rs.download("/gallery/Documents/data.csv", out)
        self.assertTrue(out.getvalue().startswith(b"well,od600"))
        with rs.openbin("/inventory/IC200/IF500", "rb") as fh:
            self.assertEqual(455, len(fh.read()))

    def test_a_partial_mount_needs_only_the_clients_it_uses(self):
        # mounts= narrows what is needed, so an ELN client alone can mount /gallery
        from rspace_client.eln.eln import ELNClient
        rs = RSpaceFilesystem(eln_client=ELNClient(self.url, "k"), mounts=["gallery", "workspace"])
        self.assertEqual(["gallery", "workspace"], rs.listdir("/"))
        self.assertIsNone(rs.inv_client)
        with self.assertRaises(ValueError):
            RSpaceFilesystem(eln_client=ELNClient(self.url, "k"), mounts=["inventory"])
        with self.assertRaises(ValueError):
            RSpaceFilesystem(mounts=["gallery"])

    def test_only_the_chosen_branches_are_mounted(self):
        """A caller can expose part of RSpace. The names and the paths below them do not
        change, so narrowing the set later does not invalidate paths to what remains."""
        rs = RSpaceFilesystem(self.url, "k", mounts=["gallery"])
        self.assertEqual(["gallery"], rs.listdir("/"))
        self.assertEqual(("gallery",), rs.mount_names)
        self.assertIn("Images", rs.listdir("/gallery"))
        self.assertIsNone(rs.inventory)
        self.assertIsNone(rs.workspace)
        with self.assertRaises(errors.ResourceNotFound):
            rs.listdir("/workspace")

    def test_mounts_are_listed_in_a_stable_order_however_they_are_given(self):
        rs = RSpaceFilesystem(self.url, "k", mounts=("workspace", "gallery", "workspace"))
        self.assertEqual(["gallery", "workspace"], rs.listdir("/"))

    def test_an_unusable_mount_set_is_refused(self):
        for bad in (["galery"], [], ["gallery", "eln"]):
            with self.assertRaises(ValueError, msg=bad):
                RSpaceFilesystem(self.url, "k", mounts=bad)

    def test_id_style_and_bare_id_aliases(self):
        rs = RSpaceFilesystem(self.url, "k", path_style="id")
        rs.gallery.gallery_id  # resolve the root outside the measurement
        before = self.calls()
        rows = list(rs.filterdir("/gallery", namespaces=["details"]))
        self.assertEqual(1, self.calls() - before)  # one call per directory, no per-child getinfo
        self.assertEqual(["GF10", "GF11", "GF12", "GF14"], [r.name for r in rows])
        self.assertTrue(all(r.is_dir and r.created is not None for r in rows))
        self.assertEqual("Images", rows[0].raw["rspace"]["name"])
        self.assertEqual(["IC201", "IC202", "IF500"], rs.listdir("/inventory/IC200"))  # bare ids
        self.assertEqual(["SA1000"], rs.listdir("/inventory/SS301"))  # the sample shortcut is its id too
        labelled = RSpaceFilesystem(self.url, "k", path_style="labelled")
        self.assertEqual("Images [GF10]", labelled.getinfo("/gallery/GF10").name)
        self.assertEqual(["protocol.docx [GL110]", "data.csv [GL111]", "data.csv [GL112]"],
                         labelled.listdir("/gallery/Documents [GF11]"))  # duplicate names stay distinct
        self.assertEqual(["Rack A [IC201]", "Rack B [IC202]", "freezer_manual.pdf [IF500]"],
                         labelled.listdir("/inventory/Freezer -80 [IC200]"))
        # a bare id resolves under every style, and the name it reports is that style's
        self.assertEqual("Images", RSpaceFilesystem(self.url, "k").getinfo("/gallery/GF10").name)

    def test_write_posture_is_shared_and_root_is_fixed(self):
        rs = RSpaceFilesystem(self.url, "k")
        for branch in (rs.gallery, rs.inventory, rs.workspace):
            self.assertEqual((False, False), (branch.writable, branch.allow_delete))
        rs = RSpaceFilesystem(self.url, "k", writable=True, allow_delete=True)
        for branch in (rs.gallery, rs.inventory, rs.workspace):
            self.assertEqual((True, True), (branch.writable, branch.allow_delete))
        payload = BytesIO(b"\x00\x01binary\r\n--x\r\n")  # bytes a sloppy multipart encoder would mangle
        payload.name = "blob.bin"
        rs.upload("/gallery/Chemistry [GF12]/blob.bin", payload)
        self.assertEqual(["blob.bin"], rs.listdir("/gallery/Chemistry [GF12]"))
        out = BytesIO()
        rs.download("/gallery/Chemistry [GF12]/blob.bin", out)
        self.assertEqual(payload.getvalue(), out.getvalue())
        rs.makedir("/gallery/TopLevel")  # the parent is the Gallery root folder
        self.assertIn("TopLevel", rs.listdir("/gallery"))
        rs.removedir("/gallery/TopLevel")
        self.assertNotIn("TopLevel", rs.listdir("/gallery"))
        payload = BytesIO(b"note")
        payload.name = "n.txt"
        rs.upload("/inventory/SS301/n.txt", payload)
        rs.remove("/inventory/SS301/n.txt")
        self.assertEqual(["sample: Plasmid pUC19"], rs.listdir("/inventory/SS301"))
        for op in (lambda: rs.makedir("/scratch"), lambda: rs.upload("/x.txt", BytesIO(b"x")),
                   lambda: rs.removedir("/gallery"), lambda: rs.remove("/gallery")):
            with self.assertRaises(errors.ResourceReadOnly):
                op()
        self.assertEqual(["gallery", "inventory", "workspace"], rs.listdir("/"))

    def test_the_fixed_top_level_cannot_be_written_to(self):
        """MountFS delegates a dozen write methods to an in-memory filesystem; without care
        they succeed there and the bytes are silently lost."""
        for rs in (RSpaceFilesystem(self.url, "k"),
                   RSpaceFilesystem(self.url, "k", writable=True, allow_delete=True)):
            for write in (lambda f: f.writetext("/a.txt", "x"),
                          lambda f: f.writebytes("/b.bin", b"x"),
                          lambda f: f.openbin("/c.txt", "wb"),
                          lambda f: f.touch("/d.txt"),
                          lambda f: f.makedirs("/e/f"),
                          lambda f: f.upload("/g.txt", BytesIO(b"x"))):
                with self.assertRaises((errors.ResourceReadOnly, errors.Unsupported)):
                    write(rs)
            self.assertEqual(["gallery", "inventory", "workspace"], rs.listdir("/"))

    def test_copying_a_gallery_file_into_rspace_links_it(self):
        """The web interface calls this "link from Gallery". Without it, a generic copy
        downloads the bytes and uploads them again, leaving a second Gallery file that the
        RSpace API cannot delete."""
        rs = RSpaceFilesystem(self.url, "k", writable=True)
        before = set(rs.listdir("/gallery/Images"))

        rs.copy("/gallery/Images/microscope.png", "/inventory/Samples/Plasmid pUC19/microscope.png")
        attached = next(i for i in rs.scandir("/inventory/Samples/Plasmid pUC19")
                        if i.name == "microscope.png")
        self.assertEqual("GL100", attached.raw["rspace"]["mediaFileGlobalId"])

        field = "/workspace/Project Alpha/Alpha protocol/Objective"
        rs.copy("/gallery/Images/microscope.png", f"{field}/microscope.png")
        self.assertIn("GL100", [i.raw["rspace"]["globalId"] for i in rs.scandir(field)])

        self.assertEqual(before, set(rs.listdir("/gallery/Images")),
                         "linking must not create a new Gallery file")

    def test_any_gallery_backed_source_links_not_just_the_gallery_mount(self):
        """A file in a document field *is* a Gallery file, so copying one into Inventory
        should link it too. Keying on the source mount rather than on what it resolves to
        silently duplicated exactly what this method exists to prevent."""
        rs = RSpaceFilesystem(self.url, "k", writable=True)
        before = set(rs.listdir("/gallery/Documents"))
        rs.copy("/workspace/Project Alpha/Alpha protocol/Results/data.csv",
                "/inventory/Samples/Plasmid pUC19/data.csv")
        attached = next(i for i in rs.scandir("/inventory/Samples/Plasmid pUC19") if i.name == "data.csv")
        self.assertEqual("GL111", attached.raw["rspace"]["mediaFileGlobalId"])
        self.assertEqual(before, set(rs.listdir("/gallery/Documents")))

    def test_a_copy_under_a_new_name_moves_the_bytes_rather_than_lying(self):
        """A link carries the Gallery file's own name, all the API offers. Asking for a
        different name has to fall through to a real copy, or the destination path would not
        exist afterwards."""
        rs = RSpaceFilesystem(self.url, "k", writable=True)
        dst = "/inventory/Samples/E. coli DH5a/renamed.png"
        rs.copy("/gallery/Images/microscope.png", dst)
        self.assertTrue(rs.exists(dst))

    def test_copy_can_preserve_time_without_failing_after_the_upload(self):
        # PyFilesystem sends the source timestamps to setinfo after a copy; RSpace
        # owns its timestamps, so they are accepted and ignored rather than failing the copy
        rs = RSpaceFilesystem(self.url, "k", writable=True)
        dst = "/inventory/Samples/E. coli DH5a/kept-time.png"
        rs.copy("/gallery/Images/microscope.png", dst, preserve_time=True)
        self.assertTrue(rs.exists(dst))
        with self.assertRaises(errors.Unsupported):
            rs.setinfo(dst, {"basic": {"name": "other.png"}})

    def test_move_refuses_before_copying_when_the_source_cannot_be_removed(self):
        # a move is copy + remove; without allow_delete the remove would fail
        # after the copy and leave a duplicate behind
        rs = RSpaceFilesystem(self.url, "k", writable=True)
        before = self.calls()
        with self.assertRaises(errors.ResourceReadOnly):
            rs.move("/inventory/IC200/freezer_manual.pdf", "/inventory/Samples/Buffer stock/freezer_manual.pdf")
        self.assertEqual(before, self.calls(), "nothing may be uploaded before the refusal")
        self.assertIn("freezer_manual.pdf", rs.listdir("/inventory/IC200"))

    def test_copy_honours_overwrite(self):
        rs = RSpaceFilesystem(self.url, "k", writable=True)
        dst = "/inventory/Samples/Buffer stock/microscope.png"
        rs.copy("/gallery/Images/microscope.png", dst)
        with self.assertRaises(errors.DestinationExists):
            rs.copy("/gallery/Images/microscope.png", dst)
        rs.copy("/gallery/Images/microscope.png", dst, overwrite=True)  # allowed

    def test_clear_name_cache_reaches_every_branch(self):
        rs = RSpaceFilesystem(self.url, "k")
        rs.listdir("/gallery/Images")
        self.assertTrue(rs.gallery._name_cache)
        rs.clear_name_cache()
        self.assertFalse(any(b._name_cache for b in (rs.gallery, rs.inventory, rs.workspace)))

    def test_a_copy_that_is_not_from_the_gallery_still_copies(self):
        """Only a Gallery source can be linked; everything else falls through to the generic
        copy, which moves the bytes. IF500 is an Inventory-only file (no mediaFileGlobalId),
        so copying it into a document field has to upload a new Gallery file."""
        rs = RSpaceFilesystem(self.url, "k", writable=True)
        source = "/inventory/IC200/freezer_manual.pdf"
        self.assertIsNone(rs.getinfo(source).raw["rspace"]["mediaFileGlobalId"])
        gallery_files_before = sum(len(files) for _, _, files in rs.walk("/gallery"))
        dst = "/workspace/Project Alpha/Alpha protocol/Objective/freezer_manual.pdf"
        rs.copy(source, dst)
        self.assertTrue(rs.exists(dst))
        self.assertTrue(rs.getinfo(dst).raw["rspace"]["globalId"].startswith("GL"))
        self.assertEqual(rs.readbytes(source), rs.readbytes(dst))
        gallery_files_after = sum(len(files) for _, _, files in rs.walk("/gallery"))
        self.assertEqual(gallery_files_before + 1, gallery_files_after, "the bytes must have moved")

    def test_gallery_section_policy_is_configurable_through_the_mount(self):
        """The Gallery routing policy must be reachable from the unified mount."""
        from rspace_client.fs.gallery import ON_MISMATCH_RAISE, ON_MISMATCH_REROUTE
        rs = RSpaceFilesystem(self.url, "k", writable=True)
        self.assertEqual(ON_MISMATCH_RAISE, rs.on_mismatch)
        self.assertEqual(ON_MISMATCH_RAISE, rs.gallery.on_mismatch)
        rerouting = RSpaceFilesystem(self.url, "k", writable=True, on_mismatch=ON_MISMATCH_REROUTE)
        self.assertEqual(ON_MISMATCH_REROUTE, rerouting.gallery.on_mismatch)
        with self.assertRaises(ValueError):
            RSpaceFilesystem(self.url, "k", on_mismatch="bogus")

    def test_upload_returns_the_branch_result(self):
        rs = RSpaceFilesystem(self.url, "k", writable=True)
        payload = BytesIO(b"x")
        payload.name = "p.png"
        placement = rs.upload("/gallery/Images [GF10]/p.png", payload)
        self.assertFalse(placement.rerouted)
        self.assertEqual("Images [GF10]", placement.requested_path.split("/")[-1])

    def test_failed_construction_closes_cleanly(self):
        """A constructor that raises must not leave __del__ throwing AttributeError."""
        with self.assertRaises(ValueError):
            RSpaceFilesystem(self.url, "k", path_style="bogus")

    def test_tree_helper_names_and_collisions(self):
        rs = RSpaceFilesystem(self.url, "k")
        text = format_tree(rs, "/gallery", max_depth=2)
        self.assertIn("Documents/", text)
        self.assertIn("data.csv (GL111)", text)   # duplicate names get their id
        self.assertIn("data.csv (GL112)", text)
        self.assertNotIn("protocol.docx (GL110)", text)  # unique names do not
        self.assertIn("freezer_manual.pdf  (455 B)", format_tree(rs, "/inventory/IC200"))
        always = format_tree(rs, "/gallery", max_depth=1, show_ids="always", sizes=False)
        self.assertIn("Images (GF10)/", always)
        top = format_tree(rs, "/", max_depth=1)
        self.assertIn("gallery/", top)
        self.assertIn("inventory/", top)

    def test_opener_reads_key_from_environment_only(self):
        host = self.url[len("http://"):]
        with patch.dict(os.environ, {"RSPACE_API_KEY": "k"}):
            rs = pyfs.open_fs(f"rspace://{host}?scheme=http")
            self.assertIsInstance(rs, RSpaceFilesystem)
            self.assertEqual(["gallery", "inventory", "workspace"], rs.listdir("/"))
            self.assertTrue(rs.getmeta()["read_only"])
            self.assertFalse(pyfs.open_fs(f"rspace://{host}?scheme=http", writeable=True).getmeta()["read_only"])
            self.assertEqual("id", pyfs.open_fs(f"rspace://{host}?scheme=http&path_style=id").path_style)
            with self.assertRaises(OpenerError):
                pyfs.open_fs(f"rspace://user:secret@{host}?scheme=http")
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("RSPACE_API_KEY", None)
            with self.assertRaises(OpenerError):
                pyfs.open_fs(f"rspace://{host}?scheme=http")

    def test_opener_cannot_be_told_which_secret_to_send_or_to_use_http_remotely(self):
        # a URL often comes from someone else; it must not pick the variable that
        # leaves the machine, nor send the real key in clear text to a remote host
        host = self.url[len("http://"):]
        with patch.dict(os.environ, {"RSPACE_API_KEY": "k", "OTHER_SECRET": "s"}):
            with self.assertRaises(OpenerError) as ctx:
                pyfs.open_fs(f"rspace://{host}?scheme=http&api_key_env=OTHER_SECRET")
            self.assertIn("RSPACE_API_KEY", str(ctx.exception))
            with self.assertRaises(OpenerError) as ctx:
                pyfs.open_fs("rspace://rspace.example.org?scheme=http")
            self.assertIn("clear text", str(ctx.exception))
            # loopback development servers keep working over http
            self.assertEqual(["gallery", "inventory", "workspace"],
                             pyfs.open_fs(f"rspace://{host}?scheme=http").listdir("/"))
        from rspace_client.fs.opener import _hostname
        self.assertEqual("::1", _hostname("[::1]:8080"))
        self.assertEqual("localhost", _hostname("localhost:8080"))
        self.assertEqual("my.host", _hostname("my.host"))

    def test_opener_reports_bad_parameters_as_opener_errors(self):
        # fs.open_fs callers handle OpenerError, not ValueError
        host = self.url[len("http://"):]
        with patch.dict(os.environ, {"RSPACE_API_KEY": "k"}):
            for bad in ("path_style=fancy", "scheme=ftp"):
                with self.assertRaises(OpenerError, msg=bad):
                    pyfs.open_fs(f"rspace://{host}?scheme=http&{bad}" if not bad.startswith("scheme")
                                 else f"rspace://{host}?{bad}")


class GalleryWriteRegressionTest(MockServerTestCase):
    """Findings from the code review of the Gallery branch, each pinned against the mock
    server so it cannot come back."""

    def test_standard_writes_reach_rspace(self):
        """fs.copy and writetext call upload() with the path of the file to create, while
        ours historically named a container; both must work."""
        fs_ = GalleryFilesystem(self.url, "k", writable=True, path_style="id")
        fs_.writetext("/GF12/notes.txt", "hello")
        source = pyfs.open_fs("mem://")
        source.writetext("report.csv", "a,b\n")
        pyfs.copy.copy_file(source, "report.csv", fs_, "/GF12/report.csv")
        explicit = BytesIO(b"x")
        explicit.name = "explicit.png"
        fs_.upload("/GF12/explicit.png", explicit)
        names = sorted(fs_.getinfo(f"/GF12/{n}").raw["rspace"]["name"] for n in fs_.listdir("/GF12"))
        self.assertEqual(["explicit.png", "notes.txt", "report.csv"], names)
        written = next(n for n in fs_.listdir("/GF12")
                       if fs_.getinfo(f"/GF12/{n}").raw["rspace"]["name"] == "notes.txt")
        self.assertEqual("hello", fs_.readtext(f"/GF12/{written}"))

    def test_closing_a_write_handle_twice_is_harmless(self):
        fs_ = GalleryFilesystem(self.url, "k", writable=True, path_style="id")
        handle = fs_.openbin("/GF12/x.txt", "wb")
        handle.write(b"bye")
        handle.close()
        handle.close()
        self.assertEqual(1, len(fs_.listdir("/GF12")))  # not uploaded twice

    def test_makedir_refuses_a_duplicate_name(self):
        fs_ = GalleryFilesystem(self.url, "k", writable=True, path_style="id")
        fs_.makedir("/Dup")
        with self.assertRaises(errors.DirectoryExists):
            fs_.makedir("/Dup")
        self.assertTrue(fs_.makedir("/Dup", recreate=True))  # recreate still returns it

    def test_scandir_validates_before_iteration(self):
        fs_ = GalleryFilesystem(self.url, "k", path_style="id")
        with self.assertRaises(errors.DirectoryExpected):
            fs_.scandir("/GF11/GL110")


if __name__ == "__main__":
    unittest.main()
