"""The unified RSpaceFilesystem mount, its copy/link semantics, the tree helper and the
rspace:// URL handling, exercised offline against the embedded mock server.

Ported from the PyFilesystem2 suite. Paths carry no leading slash and the root is ``""``;
an entry's ``name`` is its full path, so tests compare segments with
:func:`rspace_client.fs.paths.last_segment`. The PyFilesystem error classes map to the
builtin ``OSError`` family (``FileNotFoundError``, :class:`ReadOnlyError`,
``NotImplementedError``, ``IsADirectoryError``, ``FileExistsError``).
"""
import gc
import os
import sys
import tempfile
import unittest
from io import BytesIO
from unittest.mock import patch

import fsspec
import fsspec.core
from upath import UPath

from rspace_client.fs import GalleryFilesystem, ReadOnlyError, RSpaceFilesystem, format_tree
from rspace_client.fs.paths import last_segment
from .mock_server_case import MockServerTestCase

MOUNTS = ["gallery", "inventory", "workspace"]


def segments(entries):
    """The last path segment of each entry (dict) or path (str)."""
    return [last_segment(e["name"] if isinstance(e, dict) else e) for e in entries]


class RSpaceFilesystemTest(MockServerTestCase):

    def test_root_lists_the_worlds_and_shares_clients(self):
        rs = RSpaceFilesystem(self.url, "k")
        self.assertEqual(MOUNTS, rs.ls("", detail=False))
        self.assertEqual("directory", rs.info("gallery")["type"])
        self.assertEqual("directory", rs.info("")["type"])
        self.assertIs(rs.gallery.eln_client, rs.eln_client)
        self.assertIs(rs.inventory.inv_client, rs.inv_client)
        self.assertTrue(rs.read_only)

    def test_a_missing_record_behind_a_global_id_does_not_exist(self):
        # a server 404 must be a FileNotFoundError, so exists() is False
        rs = RSpaceFilesystem(self.url, "k")
        for path in ("gallery/GF99999", "gallery/GL99999", "inventory/IC99999",
                     "inventory/Samples/SA99999", "workspace/SD99999", "workspace/FL99999"):
            self.assertFalse(rs.exists(path), path)
            with self.assertRaises(FileNotFoundError, msg=path):
                rs.info(path)
        self.assertFalse(rs.exists("gallery/GF99999/anything"))
        with self.assertRaises(FileNotFoundError):
            rs.ls("nope")  # not a mount

    def test_browse_through_the_mount(self):
        rs = RSpaceFilesystem(self.url, "k")
        self.assertEqual(["gallery/Images", "gallery/Documents", "gallery/Chemistry", "gallery/Api Imports"],
                         rs.ls("gallery", detail=False))
        rows = rs.ls("gallery/Documents", detail=True)
        # two files are called data.csv; the second carries its id, and keeps its extension
        self.assertEqual(["protocol.docx", "data.csv", "data [GL112].csv"], segments(rows))
        self.assertTrue(all(r["name"].startswith("gallery/Documents/") for r in rows))
        self.assertEqual(["Rack A", "Rack B", "freezer_manual.pdf"], segments(rs.ls("inventory/IC200", detail=False)))
        walked = {p for p, _, _ in rs.walk("")}
        self.assertIn("gallery/Images/2026-09 run", walked)
        self.assertIn("inventory", walked)  # walking the whole mount works
        self.assertIn("inventory/WB user1a/Bench box", walked)
        self.assertEqual(["WB user1a", "Containers", "Samples", "Templates"],
                         segments(rs.ls("inventory", detail=False)))
        out = BytesIO()
        rs.download_fileobj("gallery/Documents/data.csv", out)
        self.assertTrue(out.getvalue().startswith(b"well,od600"))
        self.assertEqual(out.getvalue(), rs.cat_file("gallery/Documents/data.csv"))
        with rs.open("inventory/IC200/IF500", "rb") as fh:
            self.assertEqual(455, len(fh.read()))
        self.assertEqual(455, rs.info("inventory/IC200/IF500")["size"])

    def test_a_partial_mount_needs_only_the_clients_it_uses(self):
        # mounts= narrows what is needed, so an ELN client alone can mount gallery
        from rspace_client.eln.eln import ELNClient
        rs = RSpaceFilesystem(eln_client=ELNClient(self.url, "k"), mounts=["gallery", "workspace"])
        self.assertEqual(["gallery", "workspace"], rs.ls("", detail=False))
        self.assertIsNone(rs.inv_client)
        with self.assertRaises(ValueError):
            RSpaceFilesystem(eln_client=ELNClient(self.url, "k"), mounts=["inventory"])
        with self.assertRaises(ValueError):
            RSpaceFilesystem(mounts=["gallery"])

    def test_only_the_chosen_branches_are_mounted(self):
        """A caller can expose part of RSpace. The names and the paths below them do not
        change, so narrowing the set later does not invalidate paths to what remains."""
        rs = RSpaceFilesystem(self.url, "k", mounts=["gallery"])
        self.assertEqual(["gallery"], rs.ls("", detail=False))
        self.assertEqual(("gallery",), rs.mount_names)
        self.assertIn("gallery/Images", rs.ls("gallery", detail=False))
        self.assertIsNone(rs.inventory)
        self.assertIsNone(rs.workspace)
        with self.assertRaises(FileNotFoundError):
            rs.ls("workspace")
        self.assertFalse(rs.exists("workspace"))

    def test_mounts_are_listed_in_a_stable_order_however_they_are_given(self):
        rs = RSpaceFilesystem(self.url, "k", mounts=("workspace", "gallery", "workspace"))
        self.assertEqual(["gallery", "workspace"], rs.ls("", detail=False))

    def test_an_unusable_mount_set_is_refused(self):
        for bad in (["galery"], [], ["gallery", "eln"]):
            with self.assertRaises(ValueError, msg=bad):
                RSpaceFilesystem(self.url, "k", mounts=bad)

    def test_id_style_and_bare_id_aliases(self):
        rs = RSpaceFilesystem(self.url, "k", path_style="id")
        rs.gallery.gallery_id  # resolve the root outside the measurement
        before = self.calls()
        rows = rs.ls("gallery", detail=True)
        self.assertEqual(1, self.calls() - before)  # one call per directory, no per-child info
        self.assertEqual(["gallery/GF10", "gallery/GF11", "gallery/GF12", "gallery/GF14"], [r["name"] for r in rows])
        self.assertTrue(all(r["type"] == "directory" and r["created"] is not None for r in rows))
        self.assertEqual("Images", rows[0]["rspace"]["name"])
        self.assertEqual("GF10", rows[0]["globalId"])
        self.assertEqual(["IC201", "IC202", "IF500"], segments(rs.ls("inventory/IC200", detail=False)))  # bare ids
        self.assertEqual(["SA1000"], segments(rs.ls("inventory/SS301", detail=False)))  # the sample shortcut is its id too
        labelled = RSpaceFilesystem(self.url, "k", path_style="labelled")
        # fsspec convention: info()["name"] echoes the path that was asked for; the style
        # shows in the listing segment and the record is under rspace/globalId
        info = labelled.info("gallery/GF10")
        self.assertEqual("gallery/GF10", info["name"])
        self.assertEqual(("GF10", "Images", "directory"), (info["globalId"], info["rspace"]["name"], info["type"]))
        self.assertIn("gallery/Images [GF10]", labelled.ls("gallery", detail=False))
        self.assertEqual(["protocol.docx [GL110]", "data.csv [GL111]", "data.csv [GL112]"],
                         segments(labelled.ls("gallery/Documents [GF11]", detail=False)))  # duplicate names stay distinct
        self.assertEqual(["Rack A [IC201]", "Rack B [IC202]", "freezer_manual.pdf [IF500]"],
                         segments(labelled.ls("inventory/Freezer -80 [IC200]", detail=False)))
        # a bare id resolves under every style, and the listing names it in that style's way
        plain = RSpaceFilesystem(self.url, "k")
        self.assertEqual("Images", plain.info("gallery/GF10")["rspace"]["name"])
        self.assertIn("gallery/Images", plain.ls("gallery", detail=False))
        # children are prefixed with the path as it was asked for (fsspec convention)
        self.assertEqual(["gallery/GF10/2026-09 run", "gallery/GF10/microscope.png", "gallery/GF10/gel.jpg"],
                         plain.ls("gallery/GF10", detail=False))

    def test_write_posture_is_shared_and_root_is_fixed(self):
        rs = RSpaceFilesystem(self.url, "k")
        for branch in (rs.gallery, rs.inventory, rs.workspace):
            self.assertEqual((False, False), (branch.writable, branch.allow_delete))
        rs = RSpaceFilesystem(self.url, "k", writable=True, allow_delete=True)
        self.assertFalse(rs.read_only)
        for branch in (rs.gallery, rs.inventory, rs.workspace):
            self.assertEqual((True, True), (branch.writable, branch.allow_delete))
        payload = BytesIO(b"\x00\x01binary\r\n--x\r\n")  # bytes a sloppy multipart encoder would mangle
        payload.name = "blob.bin"
        rs.upload_fileobj("gallery/Chemistry [GF12]/blob.bin", payload)
        self.assertEqual(["gallery/Chemistry [GF12]/blob.bin"], rs.ls("gallery/Chemistry [GF12]", detail=False))
        out = BytesIO()
        rs.download_fileobj("gallery/Chemistry [GF12]/blob.bin", out)
        self.assertEqual(payload.getvalue(), out.getvalue())
        rs.mkdir("gallery/TopLevel")  # the parent is the Gallery root folder
        self.assertIn("gallery/TopLevel", rs.ls("gallery", detail=False))
        rs.rmdir("gallery/TopLevel")
        self.assertNotIn("gallery/TopLevel", rs.ls("gallery", detail=False))
        payload = BytesIO(b"note")
        payload.name = "n.txt"
        rs.upload_fileobj("inventory/SS301/n.txt", payload)
        self.assertIn("n.txt", segments(rs.ls("inventory/SS301", detail=False)))
        rs.rm_file("inventory/SS301/n.txt")
        self.assertEqual(["inventory/SS301/sample: Plasmid pUC19"], rs.ls("inventory/SS301", detail=False))
        for op in (lambda: rs.mkdir("scratch"), lambda: rs.upload_fileobj("x.txt", BytesIO(b"x")),
                   lambda: rs.rmdir("gallery"), lambda: rs.rm_file("gallery"), lambda: rs.rm("gallery")):
            with self.assertRaises(ReadOnlyError):
                op()
        self.assertEqual(MOUNTS, rs.ls("", detail=False))

    def test_the_fixed_top_level_cannot_be_written_to(self):
        """The top level is a fixed list of mounts; a write there must be refused rather
        than vanishing into a filesystem that is never read back, whatever the posture."""
        for rs in (RSpaceFilesystem(self.url, "k"),
                   RSpaceFilesystem(self.url, "k", writable=True, allow_delete=True)):
            for write in (lambda f: f.pipe_file("a.txt", b"x"),
                          lambda f: f.open("c.txt", "wb"),
                          lambda f: f.touch("d.txt"),
                          lambda f: f.makedirs("e"),
                          lambda f: f.mkdir("e"),
                          lambda f: f.upload_fileobj("g.txt", BytesIO(b"x")),
                          lambda f: f.put_file(__file__, "h.py"),
                          lambda f: f.cp_file("gallery/Images/microscope.png", "i.png"),
                          lambda f: f.mv("gallery/Images/microscope.png", "j.png"),
                          lambda f: f.link("k", "GL100")):
                with self.assertRaises(ReadOnlyError):
                    write(rs)
            # below a name that is not a mount there is nothing to create either
            with self.assertRaises(FileNotFoundError):
                rs.makedirs("e/f")
            with self.assertRaises(IsADirectoryError):
                rs.open("gallery", "rb")
            self.assertEqual(MOUNTS, rs.ls("", detail=False))

    def test_copying_a_gallery_file_into_rspace_links_it(self):
        """The web interface calls this "link from Gallery". Without it, a generic copy
        downloads the bytes and uploads them again, leaving a second Gallery file that the
        RSpace API cannot delete."""
        rs = RSpaceFilesystem(self.url, "k", writable=True)
        before = set(rs.ls("gallery/Images", detail=False))

        rs.cp_file("gallery/Images/microscope.png", "inventory/Samples/Plasmid pUC19/microscope.png")
        attached = next(i for i in rs.scandir("inventory/Samples/Plasmid pUC19")
                        if last_segment(i["name"]) == "microscope.png")
        self.assertEqual("GL100", attached["rspace"]["mediaFileGlobalId"])

        field = "workspace/Project Alpha/Alpha protocol/Objective"
        rs.copy("gallery/Images/microscope.png", f"{field}/microscope.png")  # fsspec's copy goes through cp_file
        self.assertIn("GL100", [i["rspace"]["globalId"] for i in rs.scandir(field)])

        self.assertEqual(before, set(rs.ls("gallery/Images", detail=False)),
                         "linking must not create a new Gallery file")

    def test_any_gallery_backed_source_links_not_just_the_gallery_mount(self):
        """A file in a document field *is* a Gallery file, so copying one into Inventory
        should link it too. Keying on the source mount rather than on what it resolves to
        silently duplicated exactly what this method exists to prevent."""
        rs = RSpaceFilesystem(self.url, "k", writable=True)
        before = set(rs.ls("gallery/Documents", detail=False))
        rs.cp_file("workspace/Project Alpha/Alpha protocol/Results/data.csv",
                   "inventory/Samples/Plasmid pUC19/data.csv")
        attached = next(i for i in rs.scandir("inventory/Samples/Plasmid pUC19")
                        if last_segment(i["name"]) == "data.csv")
        self.assertEqual("GL111", attached["rspace"]["mediaFileGlobalId"])
        self.assertEqual(before, set(rs.ls("gallery/Documents", detail=False)))

    def test_a_copy_under_a_new_name_moves_the_bytes_rather_than_lying(self):
        """A link carries the Gallery file's own name, all the API offers. Asking for a
        different name has to fall through to a real copy, or the destination path would not
        exist afterwards."""
        rs = RSpaceFilesystem(self.url, "k", writable=True)
        dst = "inventory/Samples/E. coli DH5a/renamed.png"
        rs.cp_file("gallery/Images/microscope.png", dst)
        self.assertTrue(rs.exists(dst))
        self.assertEqual(rs.cat_file("gallery/Images/microscope.png"), rs.cat_file(dst))

    # test_copy_can_preserve_time_without_failing_after_the_upload is not ported: fsspec's
    # cp_file has no preserve_time option and there is no setinfo, so there is no timestamp
    # write-back to survive. RSpace owns its timestamps in either framework.

    def test_move_refuses_before_copying_when_the_source_cannot_be_removed(self):
        # a move is copy + remove; without allow_delete the remove would fail
        # after the copy and leave a duplicate behind
        rs = RSpaceFilesystem(self.url, "k", writable=True)
        before = self.calls()
        with self.assertRaises(ReadOnlyError):
            rs.mv("inventory/IC200/freezer_manual.pdf", "inventory/Samples/Buffer stock/freezer_manual.pdf")
        self.assertEqual(before, self.calls(), "nothing may be uploaded before the refusal")
        self.assertIn("freezer_manual.pdf", segments(rs.ls("inventory/IC200", detail=False)))
        # a read-only destination is refused just as early
        before = self.calls()
        with self.assertRaises(ReadOnlyError):
            RSpaceFilesystem(self.url, "k", allow_delete=True).mv(
                "inventory/IC200/freezer_manual.pdf", "inventory/Samples/Buffer stock/freezer_manual.pdf")
        self.assertEqual(before, self.calls())

    def test_copy_honours_overwrite(self):
        """fsspec's cp_file has no overwrite flag: copying onto a destination that already
        exists is not an error, it is a second copy. For a Gallery source into Inventory
        that is a second link to the same Gallery file, and still no new Gallery file."""
        rs = RSpaceFilesystem(self.url, "k", writable=True)
        gallery_before = set(rs.ls("gallery/Images", detail=False))
        dst = "inventory/Samples/Buffer stock/microscope.png"
        rs.cp_file("gallery/Images/microscope.png", dst)
        self.assertTrue(rs.exists(dst))
        rs.cp_file("gallery/Images/microscope.png", dst)  # allowed, no FileExistsError
        linked = [i for i in rs.scandir("inventory/Samples/Buffer stock")
                  if i["rspace"].get("mediaFileGlobalId") == "GL100"]
        self.assertEqual(2, len(linked))
        self.assertEqual(gallery_before, set(rs.ls("gallery/Images", detail=False)))

    def test_clear_name_cache_reaches_every_branch(self):
        rs = RSpaceFilesystem(self.url, "k")
        rs.ls("gallery/Images")
        self.assertTrue(rs.gallery._name_cache)
        rs.clear_name_cache()
        self.assertFalse(any(b._name_cache for b in (rs.gallery, rs.inventory, rs.workspace)))

    def test_a_copy_that_is_not_from_the_gallery_still_copies(self):
        """Only a Gallery source can be linked; everything else falls through to the generic
        copy, which moves the bytes. IF500 is an Inventory-only file (no mediaFileGlobalId),
        so copying it into a document field has to upload a new Gallery file."""
        rs = RSpaceFilesystem(self.url, "k", writable=True)
        source = "inventory/IC200/freezer_manual.pdf"
        self.assertIsNone(rs.info(source)["rspace"]["mediaFileGlobalId"])
        gallery_files_before = sum(len(files) for _, _, files in rs.walk("gallery"))
        dst = "workspace/Project Alpha/Alpha protocol/Objective/freezer_manual.pdf"
        rs.cp_file(source, dst)
        self.assertTrue(rs.exists(dst))
        self.assertTrue(rs.info(dst)["rspace"]["globalId"].startswith("GL"))
        self.assertEqual(rs.cat_file(source), rs.cat_file(dst))
        gallery_files_after = sum(len(files) for _, _, files in rs.walk("gallery"))
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
        placement = rs.upload_fileobj("gallery/Images [GF10]/p.png", payload)
        self.assertFalse(placement.rerouted)
        self.assertEqual("Images [GF10]", placement.requested_path.split("/")[-1])
        self.assertTrue(placement.file_global_id.startswith("GL"))

    def test_failed_construction_closes_cleanly(self):
        """A constructor that raises must raise ValueError and nothing else: no
        AttributeError from a half-built object when it is garbage-collected."""
        with patch.object(sys, "unraisablehook") as hook:
            for construct in (lambda: RSpaceFilesystem(self.url, "k", path_style="bogus"),
                              lambda: RSpaceFilesystem(self.url, "k", mounts=["galery"]),
                              lambda: RSpaceFilesystem(self.url, "k", mounts=[]),
                              lambda: RSpaceFilesystem(mounts=["gallery"])):
                with self.assertRaises(ValueError):
                    construct()
                gc.collect()
            hook.assert_not_called()

    def test_tree_helper_names_and_collisions(self):
        rs = RSpaceFilesystem(self.url, "k")
        text = format_tree(rs, "gallery", max_depth=2)
        self.assertTrue(text.startswith("gallery/\n"))
        self.assertIn("Documents/", text)
        self.assertIn("data.csv (GL111)", text)   # duplicate names get their id
        self.assertIn("data.csv (GL112)", text)
        self.assertNotIn("protocol.docx (GL110)", text)  # unique names do not
        self.assertIn("freezer_manual.pdf  (455 B)", format_tree(rs, "inventory/IC200"))
        always = format_tree(rs, "gallery", max_depth=1, show_ids="always", sizes=False)
        self.assertIn("Images (GF10)/", always)
        top = format_tree(rs, "", max_depth=1)
        self.assertIn("gallery/", top)
        self.assertIn("inventory/", top)

    # ------------------------------------------------------------ rspace:// URLs

    @property
    def host(self):
        return self.url[len("http://"):]

    def test_url_reads_key_from_environment_only(self):
        url = f"rspace://{self.host}?scheme=http"
        self.assertEqual({"server": self.url}, RSpaceFilesystem._get_kwargs_from_urls(url))
        with patch.dict(os.environ, {"RSPACE_API_KEY": "k"}):
            rs, path = fsspec.core.url_to_fs(url)
            self.assertIsInstance(rs, RSpaceFilesystem)
            self.assertEqual(MOUNTS, rs.ls(path, detail=False))
            self.assertEqual(MOUNTS, rs.ls("", detail=False))
            self.assertTrue(rs.read_only)
            self.assertFalse(fsspec.core.url_to_fs(f"{url}&writable=1")[0].read_only)
            self.assertEqual("id", fsspec.core.url_to_fs(f"{url}&path_style=id")[0].path_style)
            self.assertEqual(("gallery",), fsspec.core.url_to_fs(f"{url}&mounts=gallery")[0].mount_names)
            with fsspec.open(f"rspace://{self.host}/gallery/Documents/data.csv?scheme=http") as fh:
                self.assertTrue(fh.read().startswith(b"well,od600"))
            self.assertEqual(MOUNTS, fsspec.filesystem("rspace", server=self.url).ls("", detail=False))
            with self.assertRaises(ValueError):
                fsspec.core.url_to_fs(f"rspace://user:secret@{self.host}?scheme=http")
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("RSPACE_API_KEY", None)
            with self.assertRaises(ValueError):
                fsspec.core.url_to_fs(url)
            with self.assertRaises(ValueError):
                RSpaceFilesystem(server=self.url)
        # an explicit key never consults the environment
        self.assertEqual(MOUNTS, RSpaceFilesystem(self.url, "k").ls("", detail=False))

    def test_url_cannot_be_told_which_secret_to_send_or_to_use_http_remotely(self):
        # a URL often comes from someone else; it must not pick the variable that
        # leaves the machine, nor send the real key in clear text to a remote host
        with patch.dict(os.environ, {"RSPACE_API_KEY": "k", "OTHER_SECRET": "s"}):
            for bad in ("api_key_env=OTHER_SECRET", "api_key=s"):
                with self.assertRaises(ValueError, msg=bad) as ctx:
                    fsspec.core.url_to_fs(f"rspace://{self.host}?scheme=http&{bad}")
                self.assertIn("RSPACE_API_KEY", str(ctx.exception))
            with self.assertRaises(ValueError) as ctx:
                fsspec.core.url_to_fs("rspace://rspace.example.org?scheme=http")
            self.assertIn("clear text", str(ctx.exception))
            # loopback development servers keep working over http
            self.assertEqual(MOUNTS, fsspec.core.url_to_fs(f"rspace://{self.host}?scheme=http")[0].ls("", detail=False))
        kwargs = RSpaceFilesystem._get_kwargs_from_urls
        self.assertEqual("http://[::1]:8080", kwargs("rspace://[::1]:8080?scheme=http")["server"])
        self.assertEqual("http://localhost:8080", kwargs("rspace://localhost:8080?scheme=http")["server"])
        self.assertEqual("https://my.host", kwargs("rspace://my.host")["server"])
        self.assertEqual("https://my.host", kwargs("rspace://my.host/gallery/Images")["server"])
        with self.assertRaises(ValueError):
            kwargs("rspace://my.host:8080?scheme=http")
        self.assertEqual({}, kwargs("file:///tmp/x"))  # not ours, nothing to say

    def test_url_reports_bad_parameters_as_value_errors(self):
        with patch.dict(os.environ, {"RSPACE_API_KEY": "k"}):
            for bad in (f"rspace://{self.host}?scheme=http&path_style=fancy",
                        f"rspace://{self.host}?scheme=ftp",
                        f"rspace://{self.host}?scheme=http&mounts=eln",
                        "rspace:///gallery"):
                with self.assertRaises(ValueError, msg=bad):
                    fsspec.core.url_to_fs(bad)

    def test_upath_lists_a_folder(self):
        with patch.dict(os.environ, {"RSPACE_API_KEY": "k"}):
            folder = UPath(f"rspace://{self.host}/gallery/Images?scheme=http")
            self.assertIsInstance(folder.fs, RSpaceFilesystem)
            self.assertEqual(self.url, folder.fs.server)
            self.assertTrue(folder.is_dir())
            self.assertEqual(["2026-09 run", "microscope.png", "gel.jpg"], [c.name for c in folder.iterdir()])
            # The generic UPath keeps a query string inside the path and joins children after
            # it, so child operations need the connection option passed as a keyword instead;
            # a real https URL has no query and does not meet this.
            folder = UPath(f"rspace://{self.host}/gallery/Images", server=self.url)
            children = list(folder.iterdir())
            self.assertEqual(["2026-09 run", "microscope.png", "gel.jpg"], [c.name for c in children])
            self.assertTrue(children[0].is_dir())
            self.assertTrue(children[1].is_file())
            self.assertTrue(children[1].read_bytes().startswith(b"\x89PNG"))
            self.assertEqual(1096, children[1].stat().st_size)
            self.assertTrue((folder / "microscope.png").exists())
            self.assertFalse((folder / "nope.png").exists())
            self.assertEqual(["microscope.png"], [p.name for p in folder.glob("*.png")])
            self.assertEqual(MOUNTS, [p.name for p in UPath(f"rspace://{self.host}/", server=self.url).iterdir()])


class GalleryWriteRegressionTest(MockServerTestCase):
    """Findings from the code review of the Gallery branch, each pinned against the mock
    server so it cannot come back."""

    def test_standard_writes_reach_rspace(self):
        """pipe_file, put_file and open('wb') name the file to create, while upload_fileobj
        historically named a container; all must work."""
        fs_ = GalleryFilesystem(self.url, "k", writable=True, path_style="id")
        fs_.pipe_file("GF12/notes.txt", b"hello")
        with tempfile.TemporaryDirectory() as tmp:
            local = os.path.join(tmp, "report.csv")
            with open(local, "w") as handle:
                handle.write("a,b\n")
            fs_.put_file(local, "GF12/report.csv")
        explicit = BytesIO(b"x")
        explicit.name = "explicit.png"
        fs_.upload_fileobj("GF12/explicit.png", explicit)
        with fs_.open("GF12/written.txt", "wb") as handle:
            handle.write(b"from a handle")
        names = sorted(fs_.info(n)["rspace"]["name"] for n in fs_.ls("GF12", detail=False))
        self.assertEqual(["explicit.png", "notes.txt", "report.csv", "written.txt"], names)
        written = next(n for n in fs_.ls("GF12", detail=False) if fs_.info(n)["rspace"]["name"] == "notes.txt")
        self.assertEqual(b"hello", fs_.cat_file(written))
        self.assertEqual("from a handle",
                         fs_.read_text(next(n for n in fs_.ls("GF12", detail=False)
                                            if fs_.info(n)["rspace"]["name"] == "written.txt")))

    def test_closing_a_write_handle_twice_is_harmless(self):
        fs_ = GalleryFilesystem(self.url, "k", writable=True, path_style="id")
        handle = fs_.open("GF12/x.txt", "wb")
        handle.write(b"bye")
        self.assertEqual([], fs_.ls("GF12"))  # nothing is sent until the handle closes
        handle.close()
        handle.close()
        self.assertEqual(1, len(fs_.ls("GF12")))  # not uploaded twice
        self.assertEqual(b"bye", fs_.cat_file(fs_.ls("GF12", detail=False)[0]))

    def test_a_transaction_defers_the_upload_to_the_end_of_the_block(self):
        fs_ = GalleryFilesystem(self.url, "k", writable=True, path_style="id")
        with fs_.transaction:
            with fs_.open("GF12/t.txt", "wb") as handle:
                handle.write(b"later")
            self.assertEqual([], fs_.ls("GF12"), "closed inside the transaction, not yet uploaded")
        self.assertEqual(1, len(fs_.ls("GF12")))
        self.assertEqual(b"later", fs_.cat_file(fs_.ls("GF12", detail=False)[0]))

    def test_mkdir_refuses_a_duplicate_name(self):
        fs_ = GalleryFilesystem(self.url, "k", writable=True, path_style="id")
        fs_.mkdir("Dup")
        with self.assertRaises(FileExistsError):
            fs_.mkdir("Dup")
        fs_.mkdir("Dup", exist_ok=True)  # still fine
        fs_.makedirs("Dup", exist_ok=True)
        self.assertEqual(1, sum(1 for e in fs_.ls("") if e["rspace"]["name"] == "Dup"))

    def test_scandir_validates_before_iteration(self):
        fs_ = GalleryFilesystem(self.url, "k", path_style="id")
        with self.assertRaises(NotADirectoryError):
            fs_.scandir("GF11/GL110")  # a file, refused at the call and not on first next()
        rs = RSpaceFilesystem(self.url, "k")
        with self.assertRaises(FileNotFoundError):
            rs.scandir("gallery/nope")
        with self.assertRaises(FileNotFoundError):
            rs.scandir("nope")


if __name__ == "__main__":
    unittest.main()
