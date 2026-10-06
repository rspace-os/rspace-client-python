"""
Live integration tests for the unified fsspec filesystem (rspace_client.fs) against a real
RSpace server. Run with `pytest -m integration`; credentials come from RSPACE_URL and
RSPACE_API_KEY (.env is loaded). Everything created is named fs-itest-* and removed
again, except Gallery files (the API cannot delete those) and nothing is touched outside
the test's own scratch folder, the Gallery Images section and one bench subsample.

These address records by global ID rather than by the text of a path segment, so they hold
whatever the path style is. The one exception is deliberate: `test_roots_are_browsable`
resolves a name against a live server, which is the only place the default style's name
lookup is exercised end to end.

Paths carry no leading slash and the root is ``""``; an entry's ``name`` is its full path,
so segments are compared through :func:`rspace_client.fs.paths.last_segment`.
"""
import time
from io import BytesIO

import pytest

from rspace_client.fs import GalleryFilesystem, ReadOnlyError, RemoteApiError, RSpaceFilesystem
from rspace_client.fs.gallery import GallerySectionMismatch
from rspace_client.fs.paths import last_segment
from rspace_client.tests.base_test import BaseApiTest

PNG_1x1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d4944415478da"
    "6364601860fd7f0f0002870180eb47ba920000000049454e44ae426082")


@pytest.mark.integration
class UnifiedFilesystemIntegrationTest(BaseApiTest):

    def setUp(self):
        super().setUp()
        self.assertClientCredentials()  # skips when RSPACE_URL / RSPACE_API_KEY are unset
        self.stamp = time.strftime("%Y%m%d-%H%M%S")
        self.rs = RSpaceFilesystem(self.rspace_url, self.rspace_apikey, writable=True, allow_delete=True)
        self.eln = self.rs.eln_client

    # ---------------------------------------------------------------- helpers

    def entries(self, path):
        """(segment, global id) per child. Tests address by global id so they do not depend
        on how the current path style spells a segment."""
        return [(last_segment(e["name"]), (e.get("rspace") or {}).get("globalId") or "")
                for e in self.rs.scandir(path)]

    def names(self, path):
        """The last segment of every child, what the old listdir returned."""
        return [name for name, _gid in self.entries(path)]

    def of_type(self, path, prefix):
        """Children whose global ID has this two-letter prefix (BE bench, SS subsample, ...)."""
        return [(name, gid) for name, gid in self.entries(path) if gid.startswith(prefix)]

    # ---------------------------------------------------------------- tests

    def test_roots_are_browsable(self):
        self.assertEqual(["gallery", "inventory", "workspace"], self.rs.ls("", detail=False))

        gallery = self.names("gallery")
        self.assertIn("Images", gallery, gallery)
        # the default style resolves a plain name against the live server
        self.assertEqual("directory", self.rs.info("gallery/Images")["type"])

        inventory = self.names("inventory")
        self.assertTrue({"Containers", "Samples", "Templates"} <= set(inventory), inventory)
        self.assertTrue(self.of_type("inventory", "BE"), "no bench listed")

        workspace = self.entries("workspace")
        self.assertFalse([n for n, gid in workspace if gid.startswith("GF")],
                         f"the Gallery root must be hidden in the Workspace: {workspace}")

    def test_workspace_document_field_roundtrip(self):
        folder_name = f"fs-itest-{self.stamp}"
        self.rs.mkdir(f"workspace/{folder_name}")
        (folder_gid,) = [gid for name, gid in self.entries("workspace") if name.startswith(folder_name)]
        folder_path = f"workspace/{folder_gid}"
        doc_id = None
        try:
            doc = self.eln.create_document(name=f"{folder_name} doc", parent_folder_id=int(folder_gid[2:]),
                                           fields=[{"content": "<p>fs itest</p>"}])
            doc_id = doc["id"]
            doc_path = f"{folder_path}/{doc['globalId']}"
            ((field_name, field_gid),) = self.entries(doc_path)
            self.assertTrue(field_gid.startswith("FD"), field_gid)
            field_path = f"{doc_path}/{field_gid}"
            self.assertEqual([], self.rs.ls(field_path, detail=False))

            for name, payload in ((f"{folder_name}.csv", b"a,b\n1,2\n"), (f"{folder_name}.png", PNG_1x1)):
                self.rs.upload_fileobj(f"{field_path}/{name}", BytesIO(payload))
            linked = self.entries(field_path)
            self.assertEqual(2, len(linked), linked)

            csv_gid = next(gid for name, gid in linked if name.endswith(".csv"))
            self.assertEqual(b"a,b\n1,2\n", self.rs.cat_file(f"{field_path}/{csv_gid}"))
            out = BytesIO()
            self.rs.download_fileobj(f"{field_path}/{csv_gid}", out)
            self.assertEqual(b"a,b\n1,2\n", out.getvalue())
            content = self.eln.get_document(doc_id)["fields"][0]["content"]
            self.assertNotIn("<fileId=", content)  # the server renders the link into markup

            for _name, gid in linked:
                self.rs.rm_file(f"{field_path}/{gid}")  # unlink only
            self.assertEqual([], self.rs.ls(field_path, detail=False))
            for _name, gid in linked:
                numeric = gid[2:]
                self.assertEqual(numeric, str(self.eln.get_file_info(numeric)["id"]))  # Gallery file kept
            self.assertIn("fs itest", self.eln.get_document(doc_id)["fields"][0]["content"])
        finally:
            if doc_id:
                self.eln.delete_document(doc_id)
            self.rs.rmdir(folder_path)
        self.assertFalse([n for n, _ in self.entries("workspace") if n.startswith(folder_name)])

    def test_inventory_attach_and_remove_on_bench_subsample(self):
        benches = self.of_type("inventory", "BE")
        if not benches:
            self.skipTest("no bench on this account")
        bench_path = f"inventory/{benches[0][1]}"
        subsamples = self.of_type(bench_path, "SS")
        if not subsamples:
            self.skipTest("no subsample on the bench to attach to")
        ss_path = f"{bench_path}/{subsamples[0][1]}"

        before = {gid for _n, gid in self.of_type(ss_path, "IF")}
        upload_name = f"fs-itest-{self.stamp}.txt"
        self.rs.upload_fileobj(f"{ss_path}/{upload_name}", BytesIO(b"fs itest attachment"))
        new = [gid for _n, gid in self.of_type(ss_path, "IF") if gid not in before]
        self.assertEqual(1, len(new), new)

        self.assertEqual(b"fs itest attachment", self.rs.cat_file(f"{ss_path}/{new[0]}"))
        self.rs.rm_file(f"{ss_path}/{new[0]}")
        self.assertEqual(before, {gid for _n, gid in self.of_type(ss_path, "IF")})
        # the shortcut to the subsample's own sample is always there
        self.assertTrue(any(n.startswith("sample:") for n, _gid in self.entries(ss_path)))

    def _first_sample_with_an_attachment_field(self):
        """(sample path, field path) for the first sample whose template gives it an
        attachment field, or None. Only some templates define one."""
        for _name, gid in self.entries("inventory/Samples"):
            sample = f"inventory/Samples/{gid}"
            fields = self.of_type(sample, "SF")
            if fields:
                return sample, f"{sample}/{fields[0][1]}"
        return None

    def _round_trip(self, container, payload=b"attachment round trip\n"):
        """Attach a file, read it back, remove it. Returns True if the bytes survived."""
        name = f"fs-itest-{self.stamp}.txt"
        self.rs.upload_fileobj(f"{container}/{name}", BytesIO(payload))
        gid = next(g for n, g in self.entries(container) if n == name)
        data = self.rs.cat_file(f"{container}/{gid}")
        self.rs.rm_file(f"{container}/{gid}")
        return data == payload

    def test_where_inventory_files_can_be_read_and_written(self):
        """The matrix, confirmed live because the server, not this library, decides most of
        it. Samples and subsamples both take their own attachments; only samples, templates
        and instruments have attachment fields, because only those have template fields at
        all; and the server refuses an attachment on a bench or a sample template outright.
        """
        found = self._first_sample_with_an_attachment_field()
        if not found:
            self.skipTest("no sample on this account has an attachment field")
        sample, field = found

        # a sample takes its own attachments
        self.assertTrue(self._round_trip(sample), "sample attachment round trip")

        # so does a subsample, which has attachments but never fields
        subsamples = self.of_type(sample, "SS")
        if subsamples:
            subsample = f"{sample}/{subsamples[0][1]}"
            self.assertTrue(self._round_trip(subsample), "subsample attachment round trip")
            self.assertEqual([], self.of_type(subsample, "SF"),
                             "a subsample must never show an attachment field")

        # an empty attachment field takes one file, and refuses a second
        if not self.rs.ls(field, detail=False):
            self.assertTrue(self._round_trip(field), "attachment field round trip")
            name = f"fs-itest-{self.stamp}-occupy.txt"
            self.rs.upload_fileobj(f"{field}/{name}", BytesIO(b"first"))
            try:
                with self.assertRaises(FileExistsError):
                    self.rs.upload_fileobj(f"{field}/second.txt", BytesIO(b"second"))
            finally:
                gid = next(g for n, g in self.entries(field) if n == name)
                self.rs.rm_file(f"{field}/{gid}")

    def test_a_bench_or_template_is_refused_before_anything_is_uploaded(self):
        """A bench and a sample template present as ordinary record folders and the server
        refuses an attachment on either. Since an upload now puts the bytes in the Gallery
        first, the refusal has to come before that, or the Gallery keeps a file nobody asked
        for and the API cannot delete it."""
        for container, what in (
            (f"inventory/{self.of_type('inventory', 'BE')[0][1]}"
             if self.of_type("inventory", "BE") else None, "bench"),
            (f"inventory/Templates/{self.entries('inventory/Templates')[0][1]}"
             if self.entries("inventory/Templates") else None, "sample template"),
        ):
            if container is None:
                continue
            with self.assertRaises(NotImplementedError, msg=what) as ctx:
                self.rs.upload_fileobj(f"{container}/fs-itest-{self.stamp}.txt", BytesIO(b"x"))
            self.assertIn("does not accept attachments", str(ctx.exception))

        # and the server would indeed have refused, which is why the guard exists; the
        # server's own explanation reaches the caller through RemoteApiError
        if self.of_type("inventory", "BE"):
            with self.assertRaises(RemoteApiError) as ctx:
                self.rs.inventory.link(self.of_type("inventory", "BE")[0][1], "GL1")
            self.assertIn("Unsupported global id type", str(ctx.exception))

    def test_an_inventory_attachment_becomes_a_gallery_item(self):
        """Uploading through the filesystem must leave a file that exists in the Gallery, not
        one that exists only inside Inventory and is reusable nowhere."""
        found = self._first_sample_with_an_attachment_field()
        if not found:
            self.skipTest("no sample on this account has an attachment field")
        sample, field = found
        targets = {"sample": sample}
        subsamples = self.of_type(sample, "SS")
        if subsamples:
            targets["subsample"] = f"{sample}/{subsamples[0][1]}"
        if not self.rs.ls(field, detail=False):
            targets["attachment field"] = field

        for label, container in targets.items():
            name = f"fs-itest-{self.stamp}-{label.replace(' ', '')}.txt"
            self.rs.upload_fileobj(f"{container}/{name}", BytesIO(b"gallery backed\n"))
            info = next(i for i in self.rs.scandir(container) if last_segment(i["name"]) == name)
            media = info["rspace"].get("mediaFileGlobalId")
            self.assertTrue(str(media).startswith("GL"),
                            f"{label}: expected a Gallery file, got {media!r}")
            # and it really is there, readable through the Gallery branch
            self.assertEqual(name, self.rs.info(f"gallery/Miscellaneous/{media}")["rspace"]["name"])
            self.rs.rm_file(f"{container}/{info['rspace']['globalId']}")

    def test_copying_a_gallery_file_into_rspace_links_it(self):
        """The generic copy would download and re-upload, leaving a duplicate in the Gallery
        that the API cannot delete."""
        found = self._first_sample_with_an_attachment_field()
        if not found:
            self.skipTest("no sample on this account has an attachment field")
        sample, _field = found
        source = next(((n, g) for n, g in self.entries("gallery/Images") if g.startswith("GL")), None)
        if source is None:
            self.skipTest("no file in the Gallery Images section to link")
        name, gallery_gid = source
        before = {g for _n, g in self.entries("gallery/Images")}

        self.rs.cp_file(f"gallery/Images/{gallery_gid}", f"{sample}/{name}")
        attached = next(i for i in self.rs.scandir(sample) if last_segment(i["name"]) == name)
        self.assertEqual(gallery_gid, attached["rspace"]["mediaFileGlobalId"])
        self.rs.rm_file(f"{sample}/{attached['rspace']['globalId']}")

        self.assertEqual(before, {g for _n, g in self.entries("gallery/Images")},
                         "linking must not add a Gallery file")

    def test_gallery_upload_and_section_routing(self):
        (images_gid,) = [gid for name, gid in self.entries("gallery") if name == "Images"]
        png_name = f"fs-itest-{self.stamp}.png"
        placement = self.rs.upload_fileobj(f"gallery/{images_gid}/{png_name}", BytesIO(PNG_1x1))
        self.assertFalse(placement.rerouted)
        self.assertEqual("Images", placement.section)

        txt_name = f"fs-itest-{self.stamp}.txt"
        with self.assertRaises(GallerySectionMismatch) as ctx:
            self.rs.upload_fileobj(f"gallery/{images_gid}/{txt_name}", BytesIO(b"not an image"))
        self.assertEqual("Images", ctx.exception.folder_section)

        rerouting = GalleryFilesystem(self.rspace_url, self.rspace_apikey, writable=True, on_mismatch="reroute")
        placement = rerouting.upload_fileobj(f"{images_gid}/{txt_name}", BytesIO(b"not an image"))
        self.assertTrue(placement.rerouted)
        self.assertEqual("Documents", placement.section)

    def test_uploads_are_named_from_the_path_not_the_file_object(self):
        """What Galaxy relies on: its datasets are all called *.dat on disk, so the name has
        to come from the path or RSpace rejects the file for the section it is going into."""
        (images_gid,) = [gid for name, gid in self.entries("gallery") if name == "Images"]
        anonymous = BytesIO(PNG_1x1)  # no .name at all
        wanted = f"fs-itest-{self.stamp}-named.png"
        placement = self.rs.upload_fileobj(f"gallery/{images_gid}/{wanted}", anonymous)
        self.assertEqual("Images", placement.section)
        stored = self.eln.get_file_info(placement.file_global_id[2:])
        self.assertEqual(wanted, stored["name"])

    def test_only_the_chosen_branches_are_mounted(self):
        eln_only = RSpaceFilesystem(self.rspace_url, self.rspace_apikey, mounts=["workspace"])
        self.assertEqual(["workspace"], eln_only.ls("", detail=False))
        self.assertTrue(eln_only.ls("workspace", detail=False) is not None)
        with self.assertRaises(FileNotFoundError):
            eln_only.ls("gallery")

    def test_read_only_default_refuses_writes(self):
        ro = RSpaceFilesystem(self.rspace_url, self.rspace_apikey)
        self.assertTrue(ro.read_only)
        with self.assertRaises(ReadOnlyError):
            ro.upload_fileobj("gallery/x.txt", BytesIO(b"x"))
        with self.assertRaises(ReadOnlyError):
            ro.mkdir("workspace/should-not-exist")
