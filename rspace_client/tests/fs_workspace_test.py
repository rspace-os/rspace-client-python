"""The ELN Workspace as folders, notebooks, documents and text fields holding files, and the
signed-document lock, against the embedded mock server."""
import unittest
from io import BytesIO

from fs import errors

from rspace_client.eln.eln import ELNClient
from rspace_client.fs import GalleryFilesystem, RSpaceFilesystem, WorkspaceFilesystem, format_tree
from .mock_server_case import MockServerTestCase


ATTACHMENT_HTML = (
    '<p>fs test</p>\n<div class="attachmentDiv mceNonEditable">\n <a href="/Streamfile/216" target="_blank"> '
    '<img class="attachmentIcon" src="/images/icons/csv.png" height="32" width="32" /> </a>\n <p class="attachmentP">'
    '<a class="attachmentLinked" id="attachOnText_216" data-type="Documents" href="/Streamfile/216" target="_blank">'
    'fs.csv</a></p>\n <div class="attachmentInfoDiv" id="attachmentInfoDiv_216">\n  <img class="attachmentInfoIcon" '
    'src="/images/getInfo12.png" />\n </div>\n</div>\n<p><img id="247-227" class="imageDropped inlineImageThumbnail" '
    'src="/thumbnail/data?sourceType=IMAGE&amp;sourceId=227&amp;sourceParentId=247&amp;width=1&amp;height=1&amp;'
    'rotation=0&amp;time=1" alt="image i.png" width="1" height="1" data-size="1-1" data-rotation="0" /></p>\n&#xa0;'
)  # verbatim shape recorded from a real RSpace 2.27 server


class StripFileReferencesTest(unittest.TestCase):
    """Unlinking must remove the markup the server renders, not just the <fileId> token."""

    def test_removes_attachment_block(self):
        from rspace_client.fs.workspace import strip_file_references
        out = strip_file_references(ATTACHMENT_HTML, 216)
        self.assertNotIn("216", out)
        self.assertIn("sourceId=227", out)  # the image stays
        self.assertIn("<p>fs test</p>", out)

    def test_removes_image_and_its_empty_paragraph(self):
        from rspace_client.fs.workspace import strip_file_references
        out = strip_file_references(ATTACHMENT_HTML, 227)
        self.assertNotIn("227", out)
        self.assertNotIn("<p></p>", out)
        self.assertIn("attachOnText_216", out)  # the csv block stays

    def test_field_id_is_not_mistaken_for_a_file_id(self):
        from rspace_client.fs.workspace import strip_file_references
        self.assertIsNone(strip_file_references(ATTACHMENT_HTML, 247))  # sourceParentId=247 is the field
        self.assertIsNone(strip_file_references(ATTACHMENT_HTML, 21))   # prefix of 216, not a match
        self.assertIsNone(strip_file_references(ATTACHMENT_HTML, 999))

    def test_literal_token_is_removed_too(self):
        from rspace_client.fs.workspace import strip_file_references
        self.assertEqual("<p>x</p>", strip_file_references("<p>x</p><fileId=5>", 5))


class WorkspaceTest(MockServerTestCase):

    def fs(self, **kw):
        return WorkspaceFilesystem(self.url, "k", **kw)

    def test_root_hides_gallery_and_templates(self):
        fs = self.fs()
        before = self.calls()
        names = fs.listdir("/")
        self.assertEqual(1, self.calls() - before)
        self.assertEqual(["Shared", "Api Inbox", "Imports", "Project Alpha", "Project Beta"], names)
        from unittest.mock import patch
        from rspace_client.fs import workspace
        with patch.object(workspace, "HIDDEN_ROOT_FOLDERS", ()):
            unhidden = self.fs(page_size=50).listdir("/")
        self.assertEqual(["Templates"], [n for n in unhidden if n not in names])
        self.assertFalse(any("[GF" in n for n in unhidden))  # the Gallery root is always hidden here
        shared = next(i for i in self.fs().scandir("/") if i.name == "Shared")
        self.assertTrue(shared.raw["rspace"]["systemFolder"])  # flag comes with the tree listing

    def test_folders_notebooks_documents_fields_files(self):
        fs = self.fs()
        self.assertEqual(["Lab notebook 2026", "Alpha protocol", "Signed protocol"],
                         fs.listdir("/Project Alpha"))
        self.assertEqual(["2026-09-15 entry", "2026-09-16 entry"],
                         fs.listdir("/Project Alpha/Lab notebook 2026"))
        before = self.calls()
        fields = list(fs.scandir("/Project Alpha [FL20]/Alpha protocol [SD42]", namespaces=["details"]))
        self.assertEqual(1, self.calls() - before)
        self.assertEqual(["Objective", "Results"], [f.name for f in fields])  # text fields only
        self.assertTrue(all(f.is_dir for f in fields))
        doc = fs.getinfo("/Project Alpha/Alpha protocol")
        self.assertEqual(5, doc.raw["rspace"]["hiddenFields"])  # attachment, number, date, string, choice
        files = list(fs.scandir("/FL20/SD42/Results", namespaces=["details"]))
        self.assertEqual(["data.csv", "plate1.png"], [f.name for f in files])
        self.assertEqual(27, files[0].size)
        self.assertIsNotNone(files[0].created)
        out = BytesIO()
        fs.download("/FL20/SD42/FD421/data.csv", out)
        self.assertTrue(out.getvalue().startswith(b"well,od600"))
        with self.assertRaises(errors.ResourceNotFound):
            fs.listdir("/FL20/SD42/FD423")  # a NUMBER field is not browsable

    def test_attachment_fields_are_not_browsable(self):
        """Text is the only ELN field type that holds files.

        rspace-web links a file to a document through a ``<fileId=N>`` token in a text
        field's HTML: every caller of ``Field.addMediaFileLink`` passes a text field. The
        ``Attachment`` type still exists in ``FieldType`` and the forms API still accepts
        it, but the form editor offers only Number, String, Text, Radio, Choice, Date and
        Time (``RSFormController.FIELD_KEYS``), so an attachment field is legacy and always
        empty. Showing it as a folder would promise something it cannot do, so it is hidden
        and counted like any other field that cannot hold a file.
        """
        fs = self.fs()
        self.assertNotIn("Raw data", fs.listdir("/FL20/SD42"))   # FD422 is an ATTACHMENT field
        self.assertEqual(5, fs.getinfo("/FL20/SD42").raw["rspace"]["hiddenFields"])
        with self.assertRaises(errors.ResourceNotFound):
            fs.listdir("/FL20/SD42/FD422")

    def test_upload_links_into_the_field_and_remove_unlinks(self):
        fs = self.fs(writable=True, allow_delete=True)
        field = "/Project Alpha [FL20]/Lab notebook 2026 [NB30]/2026-09-16 entry [SD41]/Data [FD410]"
        self.assertEqual([], fs.listdir(field))
        payload = BytesIO(b"a,b\n1,2\n")
        payload.name = "run.csv"
        fs.upload(field + "/run.csv", payload)
        self.assertEqual(["run.csv"], fs.listdir(field))
        (linked,) = fs.listdir(field)
        gid = next(iter(fs.scandir(field))).raw["rspace"]["globalId"]
        content = ELNClient(self.url, "k").get_document(41)["fields"][0]["content"]
        self.assertIn(f'attachOnText_{gid[2:]}"', content)  # the mock renders the token like the server
        self.assertNotIn("<fileId=", content)
        fs.remove(f"{field}/{linked}")
        self.assertEqual([], fs.listdir(field))
        self.assertEqual(f"{gid[2:]}", str(ELNClient(self.url, "k").get_file_info(gid[2:])["id"]))  # Gallery file kept
        with self.assertRaises(errors.ResourceNotFound):
            fs.upload("/FL20/SD42/FD422/x.txt", BytesIO(b"x"))  # ATTACHMENT field: not browsable
        with self.assertRaises(errors.Unsupported):
            fs.upload("/FL20/SD42/x.txt", BytesIO(b"x"))  # a document is not an upload target

    def test_a_locked_document_says_so_before_you_try_to_write(self):
        """Signing locks a document. Listing its fields already fetches it, so the lock can
        be surfaced there for nothing; the parent folder listing cannot say so, because the
        folder-tree endpoint does not carry the flag."""
        fs = self.fs()
        self.assertEqual(["Data (signed)"], fs.listdir("/Project Alpha/Signed protocol"))
        self.assertEqual(["Objective", "Results"], fs.listdir("/Project Alpha/Alpha protocol"))

    def test_the_lock_is_in_the_access_namespace_too(self):
        """A marker in a name is for people. A tool asking for permissions gets an answer."""
        fs = self.fs()
        signed = fs.getinfo("/Project Alpha/Signed protocol", namespaces=["access"])
        ordinary = fs.getinfo("/Project Alpha/Alpha protocol", namespaces=["access"])
        self.assertNotIn("u_w", signed.permissions.dump())
        self.assertIn("u_w", ordinary.permissions.dump())
        field = next(iter(fs.scandir("/Project Alpha/Signed protocol", namespaces=["access"])))
        self.assertNotIn("u_w", field.permissions.dump())
        self.assertTrue(field.raw["rspace"]["signed"])

    def test_a_path_stored_before_signing_still_resolves(self):
        """The marker changes a segment, so the lookup has to accept both spellings or every
        saved path into a document would break the day it was signed."""
        fs = self.fs()
        both = [fs.getinfo(f"/Project Alpha/Signed protocol/{n}").raw["rspace"]["globalId"]
                for n in ("Data", "Data (signed)")]
        self.assertEqual(["FD440", "FD440"], both)

    def test_the_marker_is_only_for_the_name_style(self):
        """The other two spell a segment for a machine to parse, and appending to
        'Data [FD440]' or to 'FD440' would break that."""
        for style in ("labelled", "id"):
            names = self.fs(path_style=style).listdir("/workspace/SD44".replace("/workspace", ""))
            self.assertFalse(any("(signed)" in n for n in names), f"{style}: {names}")

    def test_a_signed_document_is_refused_before_anything_is_uploaded(self):
        """The field update would be refused and the uploaded file stranded in the Gallery,
        which the RSpace API cannot delete."""
        fs = self.fs(writable=True)
        gallery = GalleryFilesystem(self.url, "k")
        gallery_before = sum(len(files) for _, _, files in gallery.walk("/"))
        with self.assertRaises(errors.ResourceReadOnly) as ctx:
            fs.upload("/Project Alpha/Signed protocol/Data/x.csv", BytesIO(b"x"))
        self.assertIn("signed", str(ctx.exception))
        self.assertIn("Nothing was uploaded", str(ctx.exception))
        gallery.clear_name_cache()
        self.assertEqual(gallery_before, sum(len(files) for _, _, files in gallery.walk("/")))

    def test_link_accepts_only_a_gallery_file_id(self):
        # the id is written into the document's HTML, so it must be a real one
        fs = self.fs(writable=True)
        field = "/Project Alpha/Alpha protocol/Objective"
        for bad in ("1><script>alert(1)</script>", "GF10", "SD42", "", "GL"):
            with self.assertRaises(ValueError, msg=bad):
                fs.link(field, bad)
        self.assertEqual([], fs.listdir(field))
        fs.link(field, "102")  # a bare number is fine, as is 'GL102'
        self.assertEqual(["GL102"], [i.raw["rspace"]["globalId"] for i in fs.scandir(field)])

    def test_link_and_remove_refuse_a_signed_document_too(self):
        # the same lock check for every field write, not only upload
        fs = self.fs(writable=True, allow_delete=True)
        field = "/Project Alpha/Signed protocol/Data"
        with self.assertRaises(errors.ResourceReadOnly):
            fs.link(field, "GL100")
        (linked,) = fs.listdir(field)
        with self.assertRaises(errors.ResourceReadOnly):
            fs.remove(f"{field}/{linked}")
        self.assertEqual([linked], fs.listdir(field))

    def test_makedir_creates_folders_only(self):
        fs = self.fs(writable=True, allow_delete=True)
        fs.makedir("/Project Alpha [FL20]/Analysis")
        self.assertIn("Analysis", fs.listdir("/FL20"))
        fs.makedir("/TopLevel")
        self.assertIn("TopLevel", fs.listdir("/"))
        with self.assertRaises(errors.Unsupported):
            fs.makedir("/FL20/NB30/entry")  # not inside a notebook
        with self.assertRaises(errors.Unsupported):
            fs.makedir("/FL20/SD42/field")  # not inside a document
        fs.removedir("/FL20/Analysis")
        self.assertNotIn("Analysis", fs.listdir("/FL20"))

    def test_listings_stream_without_exposing_pages(self):
        names = self.fs(page_size=3).listdir("/")  # fetched 3 at a time, but no page-N folders
        self.assertEqual(5, len(names))
        self.assertFalse(any(n.startswith("page-") for n in names))
        dirs = [p for p, _, _ in self.fs().walk("/", namespaces=["details"])]
        self.assertEqual(len(dirs), len(set(dirs)))
        self.assertIn("/Project Alpha/Alpha protocol/Results", dirs)
        text = format_tree(self.fs(), "/Project Alpha [FL20]")
        self.assertIn("Alpha protocol/", text)
        self.assertIn("Results/", text)
        self.assertIn("plate1.png", text)

    def test_mounted_in_rspace_filesystem(self):
        rs = RSpaceFilesystem(self.url, "k")
        self.assertEqual(["gallery", "inventory", "workspace"], rs.listdir("/"))
        self.assertIn("Project Alpha", rs.listdir("/workspace"))
        self.assertIs(rs.workspace.eln_client, rs.gallery.eln_client)
        out = BytesIO()
        rs.download("/workspace/FL20/SD42/FD421/GL111", out)
        self.assertEqual(27, len(out.getvalue()))
        with self.assertRaises(errors.ResourceReadOnly):
            rs.removedir("/workspace")


if __name__ == "__main__":
    unittest.main()
