"""The ELN Workspace as folders, notebooks, documents and text fields holding files, and the
signed-document lock, against the embedded mock server."""
import unittest
from io import BytesIO
from itertools import islice
from unittest.mock import patch

from rspace_client.eln.eln import ELNClient
from rspace_client.fs import GalleryFilesystem, ReadOnlyError, RSpaceFilesystem, WorkspaceFilesystem, format_tree
from rspace_client.fs import workspace
from rspace_client.fs.paths import last_segment
from rspace_client.fs.workspace import strip_file_references
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


def names(fs, path):
    """The last segments of a listing, which is what the old ``listdir`` returned."""
    return [last_segment(n) for n in fs.ls(path, detail=False)]


class StripFileReferencesTest(unittest.TestCase):
    """Unlinking must remove the markup the server renders, not just the <fileId> token."""

    def test_removes_attachment_block(self):
        out = strip_file_references(ATTACHMENT_HTML, 216)
        self.assertNotIn("216", out)
        self.assertIn("sourceId=227", out)  # the image stays
        self.assertIn("<p>fs test</p>", out)

    def test_removes_image_and_its_empty_paragraph(self):
        out = strip_file_references(ATTACHMENT_HTML, 227)
        self.assertNotIn("227", out)
        self.assertNotIn("<p></p>", out)
        self.assertIn("attachOnText_216", out)  # the csv block stays

    def test_field_id_is_not_mistaken_for_a_file_id(self):
        self.assertIsNone(strip_file_references(ATTACHMENT_HTML, 247))  # sourceParentId=247 is the field
        self.assertIsNone(strip_file_references(ATTACHMENT_HTML, 21))   # prefix of 216, not a match
        self.assertIsNone(strip_file_references(ATTACHMENT_HTML, 999))

    def test_literal_token_is_removed_too(self):
        self.assertEqual("<p>x</p>", strip_file_references("<p>x</p><fileId=5>", 5))


class WorkspaceTest(MockServerTestCase):

    def fs(self, **kw):
        return WorkspaceFilesystem(self.url, "k", **kw)

    def test_root_hides_gallery_and_templates(self):
        fs = self.fs()
        before = self.calls()
        listed = fs.ls("", detail=False)
        self.assertEqual(1, self.calls() - before)
        self.assertEqual(["Shared", "Api Inbox", "Imports", "Project Alpha", "Project Beta"], listed)
        with patch.object(workspace, "HIDDEN_ROOT_FOLDERS", ()):
            unhidden = self.fs(page_size=50).ls("", detail=False)
        self.assertEqual(["Templates"], [n for n in unhidden if n not in listed])
        self.assertFalse(any("[GF" in n for n in unhidden))  # the Gallery root is always hidden here
        shared = next(e for e in self.fs().scandir("") if last_segment(e["name"]) == "Shared")
        self.assertTrue(shared["rspace"]["systemFolder"])  # flag comes with the tree listing

    def test_folders_notebooks_documents_fields_files(self):
        fs = self.fs()
        self.assertEqual(["Lab notebook 2026", "Alpha protocol", "Signed protocol"],
                         names(fs, "Project Alpha"))
        self.assertEqual(["2026-09-15 entry", "2026-09-16 entry"],
                         names(fs, "Project Alpha/Lab notebook 2026"))
        before = self.calls()
        fields = list(fs.scandir("Project Alpha [FL20]/Alpha protocol [SD42]"))
        self.assertEqual(1, self.calls() - before)
        self.assertEqual(["Objective", "Results"], [last_segment(f["name"]) for f in fields])  # text fields only
        self.assertTrue(all(f["type"] == "directory" for f in fields))
        doc = fs.info("Project Alpha/Alpha protocol")
        self.assertEqual(5, doc["rspace"]["hiddenFields"])  # attachment, number, date, string, choice
        files = fs.ls("FL20/SD42/Results", detail=True)
        self.assertEqual(["data.csv", "plate1.png"], [last_segment(f["name"]) for f in files])
        self.assertTrue(all(f["type"] == "file" for f in files))
        self.assertEqual(27, files[0]["size"])
        self.assertIsNotNone(files[0]["created"])
        out = BytesIO()
        fs.download_fileobj("FL20/SD42/FD421/data.csv", out)
        self.assertTrue(out.getvalue().startswith(b"well,od600"))
        self.assertEqual(out.getvalue(), fs.cat_file("FL20/SD42/FD421/data.csv"))
        with fs.open("FL20/SD42/FD421/data.csv", "rb") as handle:
            self.assertEqual(out.getvalue(), handle.read())
        with self.assertRaises(FileNotFoundError):
            fs.ls("FL20/SD42/FD423")  # a NUMBER field is not browsable
        with self.assertRaises(IsADirectoryError):
            fs.cat_file("FL20/SD42/FD421")  # a field is a folder, not a file

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
        self.assertNotIn("Raw data", names(fs, "FL20/SD42"))   # FD422 is an ATTACHMENT field
        self.assertEqual(5, fs.info("FL20/SD42")["rspace"]["hiddenFields"])
        with self.assertRaises(FileNotFoundError):
            fs.ls("FL20/SD42/FD422")

    def test_upload_links_into_the_field_and_remove_unlinks(self):
        fs = self.fs(writable=True, allow_delete=True)
        field = "Project Alpha [FL20]/Lab notebook 2026 [NB30]/2026-09-16 entry [SD41]/Data [FD410]"
        self.assertEqual([], fs.ls(field, detail=False))
        payload = BytesIO(b"a,b\n1,2\n")
        payload.name = "run.csv"
        uploaded = fs.upload_fileobj(field + "/run.csv", payload)
        self.assertEqual("run.csv", uploaded["name"])
        self.assertTrue(str(uploaded["globalId"]).startswith("GL"))
        self.assertEqual(["run.csv"], names(fs, field))
        (linked,) = names(fs, field)
        gid = next(iter(fs.scandir(field)))["rspace"]["globalId"]
        self.assertEqual(uploaded["globalId"], gid)
        content = ELNClient(self.url, "k").get_document(41)["fields"][0]["content"]
        self.assertIn(f'attachOnText_{gid[2:]}"', content)  # the mock renders the token like the server
        self.assertNotIn("<fileId=", content)
        fs.rm_file(f"{field}/{linked}")
        self.assertEqual([], fs.ls(field, detail=False))
        self.assertEqual(f"{gid[2:]}", str(ELNClient(self.url, "k").get_file_info(gid[2:])["id"]))  # Gallery file kept
        with self.assertRaises(FileNotFoundError):
            fs.upload_fileobj("FL20/SD42/FD422/x.txt", BytesIO(b"x"))  # ATTACHMENT field: not browsable
        with self.assertRaises(NotImplementedError):
            fs.upload_fileobj("FL20/SD42/x.txt", BytesIO(b"x"))  # a document is not an upload target

    def test_a_locked_document_says_so_before_you_try_to_write(self):
        """Signing locks a document. Listing its fields already fetches it, so the lock can
        be surfaced there for nothing; the parent folder listing cannot say so, because the
        folder-tree endpoint does not carry the flag."""
        fs = self.fs()
        self.assertEqual(["Data (signed)"], names(fs, "Project Alpha/Signed protocol"))
        self.assertEqual(["Objective", "Results"], names(fs, "Project Alpha/Alpha protocol"))

    def test_the_lock_is_in_the_access_namespace_too(self):
        """A marker in a name is for people. A tool asking for permissions gets an answer:
        ``writable`` is False for a signed document and its fields, True otherwise."""
        fs = self.fs()
        signed = fs.info("Project Alpha/Signed protocol")
        ordinary = fs.info("Project Alpha/Alpha protocol")
        self.assertIs(False, signed["writable"])
        self.assertIs(True, ordinary["writable"])
        field = next(iter(fs.scandir("Project Alpha/Signed protocol")))
        self.assertIs(False, field["writable"])
        self.assertTrue(field["rspace"]["signed"])
        ordinary_field = next(iter(fs.scandir("Project Alpha/Alpha protocol")))
        self.assertIs(True, ordinary_field["writable"])
        self.assertFalse(ordinary_field["rspace"]["signed"])

    def test_a_path_stored_before_signing_still_resolves(self):
        """The marker changes a segment, so the lookup has to accept both spellings or every
        saved path into a document would break the day it was signed."""
        fs = self.fs()
        both = [fs.info(f"Project Alpha/Signed protocol/{n}")["rspace"]["globalId"]
                for n in ("Data", "Data (signed)")]
        self.assertEqual(["FD440", "FD440"], both)

    def test_the_marker_is_only_for_the_name_style(self):
        """The other two spell a segment for a machine to parse, and appending to
        'Data [FD440]' or to 'FD440' would break that."""
        for style in ("labelled", "id"):
            listed = self.fs(path_style=style).ls("SD44", detail=False)
            self.assertFalse(any("(signed)" in n for n in listed), f"{style}: {listed}")

    def test_a_signed_document_is_refused_before_anything_is_uploaded(self):
        """The field update would be refused and the uploaded file stranded in the Gallery,
        which the RSpace API cannot delete."""
        fs = self.fs(writable=True)
        gallery = GalleryFilesystem(self.url, "k")
        gallery_before = sum(len(files) for _, _, files in gallery.walk(""))
        self.assertGreater(gallery_before, 0)
        with self.assertRaises(ReadOnlyError) as ctx:
            fs.upload_fileobj("Project Alpha/Signed protocol/Data/x.csv", BytesIO(b"x"))
        self.assertIn("signed", str(ctx.exception))
        self.assertIn("Nothing was uploaded", str(ctx.exception))
        self.assertIsInstance(ctx.exception, PermissionError)
        gallery.clear_name_cache()
        self.assertEqual(gallery_before, sum(len(files) for _, _, files in gallery.walk("")))

    def test_link_accepts_only_a_gallery_file_id(self):
        # the id is written into the document's HTML, so it must be a real one
        fs = self.fs(writable=True)
        field = "Project Alpha/Alpha protocol/Objective"
        for bad in ("1><script>alert(1)</script>", "GF10", "SD42", "", "GL"):
            with self.assertRaises(ValueError, msg=bad):
                fs.link(field, bad)
        self.assertEqual([], fs.ls(field, detail=False))
        linked = fs.link(field, "102")  # a bare number is fine, as is 'GL102'
        self.assertEqual("GL102", linked["globalId"])
        self.assertEqual(["GL102"], [e["rspace"]["globalId"] for e in fs.scandir(field)])
        with self.assertRaises(NotImplementedError):
            fs.link("Project Alpha/Alpha protocol", "GL102")  # a document is not a link target

    def test_link_and_remove_refuse_a_signed_document_too(self):
        # the same lock check for every field write, not only upload
        fs = self.fs(writable=True, allow_delete=True)
        field = "Project Alpha/Signed protocol/Data"
        with self.assertRaises(ReadOnlyError):
            fs.link(field, "GL100")
        (linked,) = fs.ls(field, detail=False)
        with self.assertRaises(ReadOnlyError):
            fs.rm_file(linked)
        self.assertEqual([linked], fs.ls(field, detail=False))

    def test_makedir_creates_folders_only(self):
        fs = self.fs(writable=True, allow_delete=True)
        self.assertIsNone(fs.mkdir("Project Alpha [FL20]/Analysis"))
        self.assertIn("Analysis", names(fs, "FL20"))
        fs.mkdir("TopLevel")
        self.assertIn("TopLevel", names(fs, ""))
        with self.assertRaises(NotImplementedError):
            fs.mkdir("FL20/NB30/entry")  # not inside a notebook
        with self.assertRaises(NotImplementedError):
            fs.mkdir("FL20/SD42/field")  # not inside a document
        with self.assertRaises(NotImplementedError):
            fs.rmdir("FL20/NB30")  # a notebook is not a folder to remove here
        fs.rmdir("FL20/Analysis")
        self.assertNotIn("Analysis", names(fs, "FL20"))

    def test_listings_stream_without_exposing_pages(self):
        fs = self.fs(page_size=3)
        listed = fs.ls("", detail=False)  # fetched 3 at a time, but no page-N folders
        self.assertEqual(5, len(listed))
        self.assertFalse(any(n.startswith("page-") for n in listed))
        # the first visible record is on the first page: stopping there costs one request
        before = self.calls()
        first = list(islice(fs.scandir(""), 1))
        self.assertEqual(["Shared"], [last_segment(e["name"]) for e in first])
        self.assertEqual(1, self.calls() - before)
        before = self.calls()
        self.assertEqual(5, len(list(fs.scandir(""))))  # 7 records in pages of 3
        self.assertEqual(3, self.calls() - before)
        dirs = [p for p, _, _ in self.fs().walk("", detail=True)]
        self.assertEqual(len(dirs), len(set(dirs)))
        self.assertIn("Project Alpha/Alpha protocol/Results", dirs)
        text = format_tree(self.fs(), "Project Alpha [FL20]")
        self.assertIn("Alpha protocol/", text)
        self.assertIn("Results/", text)
        self.assertIn("plate1.png", text)

    def test_mounted_in_rspace_filesystem(self):
        rs = RSpaceFilesystem(self.url, "k")
        self.assertEqual(["gallery", "inventory", "workspace"], rs.ls("", detail=False))
        self.assertIn("workspace/Project Alpha", rs.ls("workspace", detail=False))
        self.assertIs(rs.workspace.eln_client, rs.gallery.eln_client)
        self.assertIsInstance(rs.workspace, WorkspaceFilesystem)
        out = BytesIO()
        rs.download_fileobj("workspace/FL20/SD42/FD421/GL111", out)
        self.assertEqual(27, len(out.getvalue()))
        self.assertEqual(out.getvalue(), rs.cat_file("workspace/FL20/SD42/FD421/GL111"))
        with self.assertRaises(ReadOnlyError):
            rs.rmdir("workspace")


if __name__ == "__main__":
    unittest.main()
