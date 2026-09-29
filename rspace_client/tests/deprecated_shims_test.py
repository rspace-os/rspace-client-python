"""
The deprecated ``rspace_client.eln.fs.GalleryFilesystem`` and
``rspace_client.inv.attachment_fs.InventoryAttachmentFilesystem`` are thin shims over
``rspace_client.fs``. Each historical promise the shims keep is pinned here once, against
the embedded mock server; the section-mismatch policy is pinned with a MagicMock client
because the mock does not enforce the Gallery's media-type rule.
"""
import unittest
import warnings
from io import BytesIO
from unittest.mock import MagicMock, patch

from fs import errors

from rspace_client.client_base import ClientBase
from rspace_client.eln.fs import GallerySectionMismatch  # noqa: E402  (the shim re-export under test)
from rspace_client.fs.base import RSpaceInfo
from .mock_server_case import MockServerTestCase


def quietly(factory, *args, **kwargs):
    """Build a shim without the DeprecationWarning it is required to emit."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return factory(*args, **kwargs)


def named(payload: bytes, name: str) -> BytesIO:
    file = BytesIO(payload)
    file.name = name
    return file


class GalleryShimTest(MockServerTestCase):

    def shim(self, **kw):
        from rspace_client.eln.fs import GalleryFilesystem
        return quietly(GalleryFilesystem, self.url, "k", **kw)

    def test_construction_warns_and_keeps_the_old_defaults(self):
        from rspace_client.eln import fs as old
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            fs = old.GalleryFilesystem(self.url, "k")
        self.assertTrue(any(issubclass(w.category, DeprecationWarning) for w in caught))
        self.assertTrue(fs.writable and fs.allow_delete)
        self.assertEqual("id", fs.path_style)
        self.assertEqual(["GF10", "GF11", "GF12", "GF14"], fs.listdir("/"))  # bare global ids
        self.assertFalse(fs.getmeta()["read_only"])

    def test_upload_takes_the_folder_and_names_the_file_after_the_file_object(self):
        fs = self.shim()
        payload = named(b"a,b\n1,2\n", "report.csv")
        self.assertEqual({}, fs._upload_kwargs("report.csv"))  # never an explicit filename
        with patch.object(fs.eln_client, "_post_multipart", wraps=fs.eln_client._post_multipart) as post:
            placement = fs.upload("/GF12", payload)
        self.assertIs(payload, post.call_args.kwargs["files"]["file"])  # the bare file, not a (name, file) tuple
        (new,) = fs.listdir("/GF12")
        self.assertEqual("report.csv", fs.getinfo(f"/GF12/{new}").raw["rspace"]["name"])
        self.assertEqual(new, placement.file_global_id)
        self.assertEqual(("GF12", "Chemistry", "/GF12", False),
                         (placement.folder_global_id, placement.section, placement.requested_path, placement.rerouted))
        self.assertEqual(b"a,b\n1,2\n", fs.readbytes(f"/GF12/{new}"))

    def test_upload_file_returning_none_does_not_break_the_placement(self):
        """Galaxy's file source monkeypatches eln_client.upload_file with a wrapper that
        returns None (see galaxy_plugin_contract_test); a successful upload must still
        hand back a Placement."""
        fs = self.shim()
        fs.eln_client.upload_file = MagicMock(return_value=None)
        placement = fs.upload("/GF12", BytesIO(b"x"))
        fs.eln_client.upload_file.assert_called_once()
        self.assertFalse(placement.rerouted)
        self.assertIsNone(placement.file_global_id)
        self.assertEqual("Gallery", placement.path)

    def test_removedir_accepts_the_pre_2_8_kwargs(self):
        fs = self.shim()
        with self.assertRaises(errors.DirectoryNotEmpty):
            fs.removedir("/GF11", recursive=False, force=False)
        self.assertIn("GF11", fs.listdir("/"))
        fs.makedir("/Scratch")
        (created,) = [g for g in fs.listdir("/") if g not in ("GF10", "GF11", "GF12", "GF14")]
        fs.removedir("/" + created, recursive=True, force=True)  # neither was ever honoured
        self.assertNotIn(created, fs.listdir("/"))

    def test_info_objects_and_the_historical_reexports(self):
        from rspace_client.eln import fs as old
        from rspace_client.fs import gallery
        info = self.shim().getinfo("/GF11")
        self.assertIsInstance(info, old.GalleryInfo)
        self.assertIs(old.GalleryInfo, RSpaceInfo)
        self.assertEqual("GF11", info.globalId)  # attribute, not the PyFilesystem name
        self.assertEqual("123", old.path_to_id("/GF1/GF123"))
        self.assertTrue(old.is_folder("/GF123"))
        self.assertFalse(old.is_folder("/GF1/GL123"))
        for name in ("GallerySectionMismatch", "Placement", "classify_media_section",
                     "ON_MISMATCH_RAISE", "ON_MISMATCH_REROUTE", "MISCELLANEOUS_SECTION"):
            self.assertIs(getattr(old, name), getattr(gallery, name), name)


class GalleryShimMismatchTest(unittest.TestCase):
    """The section-mismatch policy, against a client that rejects the folder the way a real
    server does. GF123 is an Images folder; the retry without a folder lands in GF555."""

    def shim(self, **kw):
        from rspace_client.eln.fs import GalleryFilesystem
        client = MagicMock()
        folders = {123: {"id": 123, "globalId": "GF123", "name": "Test Folder", "mediaType": "Images"},
                   555: {"id": 555, "globalId": "GF555", "name": "Api Inbox", "mediaType": "Documents"}}
        client.get_folder.side_effect = lambda fid: folders[int(fid)]
        rejected = ClientBase.ApiError("File type not allowed in this folder", response_status_code=400)

        def upload_file(file, folder_id=None, **kwargs):
            if folder_id is not None:
                raise rejected
            return {"id": 999, "globalId": "GL999", "name": "data.pdf", "parentFolderId": 555}
        client.upload_file.side_effect = upload_file
        return quietly(GalleryFilesystem, eln_client=client, **kw), client

    def test_a_wrong_section_raises_a_mismatch_that_names_both_sections(self):
        fs, _ = self.shim()
        with self.assertRaises(GallerySectionMismatch) as ctx:
            fs.upload("/GF123", named(b"%PDF-1.4 fake", "data.pdf"))
        err = ctx.exception
        self.assertEqual(("Images", "GF123", "Documents"),
                         (err.folder_section, err.folder_global_id, err.file_media_type))
        for fragment in ("Images", "data.pdf", "File type not allowed"):
            self.assertIn(fragment, str(err))
        self.assertEqual("Miscellaneous", self._mismatch(fs, "archive.zip").file_media_type)

    def _mismatch(self, fs, filename):
        with self.assertRaises(GallerySectionMismatch) as ctx:
            fs.upload("/GF123", named(b"x", filename))
        return ctx.exception

    def test_reroute_retries_without_a_folder_per_call_or_by_constructor_policy(self):
        fs, client = self.shim()
        placement = fs.upload("/GF123", named(b"%PDF-1.4 fake", "data.pdf"), on_mismatch="reroute")
        self.assertTrue(placement.rerouted)
        self.assertEqual(("GL999", "Documents", "GF555", "/GF123", "Gallery/Documents/Api Inbox"),
                         (placement.file_global_id, placement.section, placement.folder_global_id,
                          placement.requested_path, placement.path))
        self.assertEqual(2, client.upload_file.call_count)
        self.assertEqual("123", client.upload_file.call_args_list[0].args[1])  # first: the folder asked for
        self.assertIsNone(client.upload_file.call_args_list[1].args[1])       # then: let the server route it
        rerouting, _ = self.shim(on_mismatch="reroute")
        self.assertTrue(rerouting.upload("/GF123", named(b"x", "data.pdf")).rerouted)

    def test_policy_edges(self):
        fs, client = self.shim()
        client.upload_file.side_effect = ClientBase.ApiError("nope", response_status_code=400)
        with self.assertRaises(ClientBase.ApiError) as ctx:
            fs.upload("", BytesIO(b"x"))  # no folder: the server routed it, so this is no mismatch
        self.assertNotIsInstance(ctx.exception, GallerySectionMismatch)
        with self.assertRaises(ValueError):
            fs.upload("/GF123", BytesIO(b"x"), on_mismatch="bogus")
        with self.assertRaises(ValueError):
            self.shim(on_mismatch="bogus")


class InventoryShimTest(MockServerTestCase):

    def shim(self, **kw):
        from rspace_client.inv.attachment_fs import InventoryAttachmentFilesystem
        return quietly(InventoryAttachmentFilesystem, self.url, "k", **kw)

    def test_construction_warns_and_keeps_the_old_defaults_from_both_import_paths(self):
        from rspace_client.inv import attachment_fs as old
        from rspace_client.inv import fs as documented  # GitHub issue #57
        self.assertIs(old.InventoryAttachmentFilesystem, documented.InventoryAttachmentFilesystem)
        self.assertIs(old.InventoryAttachmentInfo, documented.InventoryAttachmentInfo)
        self.assertIs(old.InventoryAttachmentInfo, RSpaceInfo)
        for module in (old, documented):
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                fs = module.InventoryAttachmentFilesystem(self.url, "k")
            self.assertTrue(any(issubclass(w.category, DeprecationWarning) for w in caught))
            self.assertTrue(fs.writable and fs.allow_delete)
            self.assertEqual("id", fs.path_style)
            self.assertFalse(fs.via_gallery)  # historical: bytes became an Inventory-only file
        import rspace_client.fs
        self.assertFalse(hasattr(rspace_client.fs, "InventoryAttachmentFilesystem"))  # one name, one set of defaults

    def test_a_record_lists_its_attachments_only(self):
        fs = self.shim()
        self.assertEqual(["IF500"], fs.listdir("/IC200"))  # not the racks inside the freezer
        self.assertEqual(["IF501"], fs.listdir("/SA1000"))  # not the subsamples or the attachment field
        self.assertEqual(["IF502"], fs.listdir("/SS300"))  # not the sample shortcut
        self.assertEqual(["IF503"], fs.listdir("/IT1"))
        self.assertEqual("IF500", fs.getinfo("/IC200/IF500").globalId)
        self.assertEqual(455, fs.getinfo("/IC200/IF500").size)

    def test_upload_takes_the_record_and_names_the_file_after_the_file_object(self):
        fs = self.shim()
        payload = named(b"note", "note.txt")
        self.assertEqual({}, fs._upload_kwargs("note.txt"))
        with patch.object(fs.inv_client, "_post_multipart", wraps=fs.inv_client._post_multipart) as post:
            fs.upload("/SS301", payload)
        self.assertIs(payload, post.call_args.kwargs["files"]["file"])
        (new,) = fs.listdir("/SS301")
        info = fs.getinfo(f"/SS301/{new}")
        self.assertEqual("note.txt", info.raw["rspace"]["name"])
        self.assertIsNone(info.raw["rspace"]["mediaFileGlobalId"])  # Inventory-only, as it always was
        fs.remove(f"/SS301/{new}")  # allow_delete is on by default
        self.assertEqual([], fs.listdir("/SS301"))


if __name__ == "__main__":
    unittest.main()
