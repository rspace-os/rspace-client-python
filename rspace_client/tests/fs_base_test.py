"""
Unit tests for the shared PyFilesystem base (rspace_client.fs.base) and the Gallery
and Inventory branches built on it. No network: the RSpace clients are replaced with
MagicMocks. The deprecated shims are covered in deprecated_shims_test.py.
"""
import unittest
from datetime import timezone
from io import BytesIO
import unittest.mock
from unittest.mock import MagicMock

from fs import errors

from rspace_client.client_base import ClientBase
from rspace_client.fs import GalleryFilesystem, InventoryFilesystem, WorkspaceFilesystem, make_info
from rspace_client.fs.base import to_epoch


class MakeInfoTest(unittest.TestCase):

    def test_iso_and_millis_timestamps_become_epoch_seconds(self):
        self.assertAlmostEqual(to_epoch("2026-09-01T09:00:00.000Z"), 1788253200.0)
        self.assertAlmostEqual(to_epoch(1788253200000), 1788253200.0)
        self.assertIsNone(to_epoch(None))
        self.assertIsNone(to_epoch("not a date"))

    def test_details_and_rspace_namespaces(self):
        info = make_info("GL5", False, raw={"globalId": "GL5", "name": "data.csv"}, size=27,
                         created="2026-09-01T09:00:00.000Z", modified="2026-09-02T09:00:00.000Z")
        self.assertEqual("GL5", info.name)
        self.assertFalse(info.is_dir)
        self.assertEqual(27, info.size)
        self.assertEqual(2026, info.created.astimezone(timezone.utc).year)
        self.assertEqual(2, info.modified.astimezone(timezone.utc).day)
        self.assertEqual("data.csv", info.rspace_name)
        self.assertEqual("GL5", info.global_id)

    def test_directory_info(self):
        info = make_info("GF1", True)
        self.assertTrue(info.is_dir)
        self.assertIsNone(info.size)
        self.assertIsNone(info.created)


def gallery_with_mock_client(**kwargs):
    client = MagicMock()
    client.list_folder_tree.side_effect = lambda folder_id=None, typesToInclude=[], **kw: {
        None: {"records": [{"id": 2, "globalId": "FL2", "name": "Gallery"}]},
        "2": {"records": [
            {"id": 10, "globalId": "GF10", "name": "Images", "created": "2026-09-01T09:01:00.000Z"},
            {"id": 100, "globalId": "GL100", "name": "a.png", "created": "2026-09-01T09:02:00.000Z", "size": 5},
        ]},
        2: {"records": [
            {"id": 10, "globalId": "GF10", "name": "Images", "created": "2026-09-01T09:01:00.000Z"},
            {"id": 100, "globalId": "GL100", "name": "a.png", "created": "2026-09-01T09:02:00.000Z", "size": 5},
        ]},
        "10": {"records": []},
    }[folder_id]
    client.link_exists.return_value = False
    client.get_folder.return_value = {"id": 10, "globalId": "GF10", "name": "Images"}
    client.get_file_info.return_value = {"id": 100, "globalId": "GL100", "name": "a.png", "size": 5}
    client.create_folder.return_value = {"id": 77, "globalId": "GF77", "name": "new"}
    kwargs.setdefault("path_style", "id")
    return GalleryFilesystem(eln_client=client, **kwargs), client


class GalleryFilesystemTest(unittest.TestCase):

    def test_root_is_resolved_lazily(self):
        fs, client = gallery_with_mock_client()
        client.list_folder_tree.assert_not_called()  # no network in the constructor
        self.assertEqual(["GF10", "GL100"], fs.listdir("/"))
        self.assertEqual(2, fs.gallery_id)

    def test_missing_gallery_folder_is_a_clear_error(self):
        client = MagicMock()
        client.list_folder_tree.return_value = {"records": [{"id": 1, "name": "Something else"}]}
        client.link_exists.return_value = False
        with self.assertRaises(errors.ResourceNotFound):
            GalleryFilesystem(eln_client=client).listdir("/")

    def test_details_are_topped_up_when_the_listing_omits_size(self):
        """Real folder-tree items have no size; consumers such as Galaxy require an int."""
        fs, client = gallery_with_mock_client()
        listing = {"records": [{"id": 100, "globalId": "GL100", "name": "a.png",
                                "created": "2026-09-01T09:02:00.000Z"}]}  # no 'size'
        client.list_folder_tree.side_effect = None
        client.list_folder_tree.return_value = listing
        fs._gallery_id = 2
        self.assertIsNone(next(iter(fs.scandir("/"))).size)  # basic listing: one call, no size
        client.get_file_info.assert_not_called()
        info = next(iter(fs.scandir("/", namespaces=["details"])))
        client.get_file_info.assert_called_once_with(100)
        self.assertEqual(5, info.size)

    def test_scandir_uses_one_listing_call_and_carries_details(self):
        fs, client = gallery_with_mock_client()
        infos = list(fs.scandir("/", namespaces=["details"]))
        self.assertEqual(["GF10", "GL100"], [i.name for i in infos])
        self.assertEqual([True, False], [i.is_dir for i in infos])
        self.assertEqual(5, infos[1].size)
        self.assertIsNotNone(infos[1].created)
        self.assertEqual("a.png", infos[1].raw["rspace"]["name"])
        client.get_folder.assert_not_called()  # no per-child getinfo
        client.get_file_info.assert_not_called()

    def test_getinfo_root_and_children(self):
        fs, _ = gallery_with_mock_client()
        self.assertTrue(fs.getinfo("/").is_dir)
        self.assertEqual("GF10", fs.getinfo("/GF10").name)
        info = fs.getinfo("GF10/GL100")
        self.assertEqual("GL100", info.name)
        self.assertFalse(info.is_dir)
        with self.assertRaises(errors.ResourceNotFound):
            fs.getinfo("/XX1")

    def test_writable_allows_upload_and_makedir(self):
        fs, client = gallery_with_mock_client(writable=True)
        self.assertFalse(fs.getmeta()["read_only"])
        payload = BytesIO(b"x")
        fs.upload("/GF10/x.png", payload)
        client.upload_file.assert_called_once_with(payload, "10", filename="x.png")
        fs.upload("/x.png", payload)  # directly under the root -> API default folder
        client.upload_file.assert_called_with(payload, None, filename="x.png")
        fs.makedir("/GF10/new")
        client.create_folder.assert_called_once_with("new", "10")

    def test_makedir_at_root_targets_gallery_root(self):
        fs, client = gallery_with_mock_client(writable=True)
        fs.makedir("/new")
        client.create_folder.assert_called_once_with("new", 2)

    def test_removedir_reaches_the_client_but_never_for_the_root(self):
        fs, client = gallery_with_mock_client(allow_delete=True)
        fs.removedir("/GF10")
        client.delete_folder.assert_called_once_with("10")
        with self.assertRaises(errors.RemoveRootError):
            fs.removedir("/")

    def test_openbin_read_downloads(self):
        fs, client = gallery_with_mock_client()
        client.download_file.side_effect = lambda fid, fh: fh.write(b"bytes")
        with fs.openbin("/GF10/GL100", "rb") as fh:
            self.assertEqual(b"bytes", fh.read())


def inventory_with_mock_client(**kwargs):
    client = MagicMock()
    attachment = {"id": 5, "globalId": "IF5", "name": "map.gb", "size": 9,
                  "created": "2026-09-01T09:00:00.000Z", "parentGlobalId": "IC1"}
    client.get_container_by_id.return_value = {"id": 1, "globalId": "IC1", "name": "Freezer",
                                               "created": "2026-09-01T08:00:00.000Z",
                                               "attachments": [attachment]}
    client.get_attachment_by_id.return_value = attachment
    kwargs.setdefault("path_style", "id")
    return InventoryFilesystem(inv_client=client, **kwargs), client


class InventoryFilesystemTest(unittest.TestCase):

    def test_info_name_is_the_last_segment_not_the_full_path(self):
        fs, _ = inventory_with_mock_client()
        self.assertEqual("IF5", fs.getinfo("/IC1/IF5").name)  # the segment, not the path
        self.assertEqual("IF5", fs.getinfo("IF5").name)
        self.assertEqual("map.gb", fs.getinfo("/IC1/IF5").raw["rspace"]["name"])

    def test_record_is_a_directory(self):
        fs, client = inventory_with_mock_client()
        info = fs.getinfo("/IC1")
        # getinfo describes the record itself, so it does not pay for the container's contents
        client.get_container_by_id.assert_called_with("1")
        self.assertTrue(info.is_dir)
        self.assertEqual("IC1", info.name)
        self.assertEqual("Freezer", info.raw["rspace"]["name"])

    def test_listing_a_container_asks_for_its_contents(self):
        fs, client = inventory_with_mock_client()
        list(fs.scandir("/IC1"))
        client.get_container_by_id.assert_called_with("1", include_content=True)

    def test_scandir_builds_children_from_the_record(self):
        fs, client = inventory_with_mock_client()
        infos = list(fs.scandir("/IC1", namespaces=["details"]))
        self.assertEqual(["IF5"], [i.name for i in infos])  # container with no content: attachments only
        self.assertEqual(9, infos[0].size)
        self.assertIsNotNone(infos[0].created)
        client.get_attachment_by_id.assert_not_called()
        self.assertEqual(["IF5"], fs.listdir("/IC1"))

    def test_root_lists_benches_and_sections(self):
        fs, client = inventory_with_mock_client()
        client.get_workbenches.return_value = [{"id": 1, "globalId": "BE1", "name": "WB me", "cType": "WORKBENCH"}]
        self.assertEqual(["BE1", "Containers", "Samples", "Templates"], fs.listdir("/"))
        self.assertTrue(fs.getinfo("/").is_dir)
        self.assertTrue(fs.getinfo("/Containers").is_dir)
        client.get_container_by_id.assert_not_called()

    def test_upload_and_remove_reach_the_client(self):
        fs, client = inventory_with_mock_client(writable=True, allow_delete=True)
        payload = BytesIO(b"x")
        fs.upload("/IC1/x.txt", payload)
        client.upload_attachment_by_global_id.assert_called_once_with("IC1", payload, filename="x.txt")
        fs.remove("/IC1/IF5")
        client.delete_attachment_by_id.assert_called_once_with("5")


def branch_with_mock_client(cls, **posture):
    client = MagicMock()
    fs = cls(inv_client=client, **posture) if cls is InventoryFilesystem else cls(eln_client=client, **posture)
    return fs, client


#: every way of changing the server that a branch filesystem offers
MUTATIONS = {
    "upload": lambda f: f.upload("/GF10/x.txt", BytesIO(b"x")),
    "makedir": lambda f: f.makedir("/GF10/new"),
    "removedir": lambda f: f.removedir("/GF10"),
    "remove": lambda f: f.remove("/GF10/GL1"),
    "link": lambda f: f.link("/GF10", "GL1"),
    "setinfo": lambda f: f.setinfo("/GF10/GL1", {"basic": {"name": "y"}}),
    "openbin 'wb'": lambda f: f.openbin("/GF10/GL1", "wb"),
    "writetext": lambda f: f.writetext("/GF10/x.txt", "x"),
    "move": lambda f: f.move("/GF10/GL1", "/GF10/GL2"),
}
DELETIONS = ("remove", "removedir", "move")

#: what a branch does not offer at all is refused the same way however it was opened
NOT_OFFERED = {
    GalleryFilesystem: {"remove": errors.Unsupported,     # the RSpace API cannot delete Gallery files
                        "link": AttributeError},          # a Gallery file is already in the Gallery
    InventoryFilesystem: {"makedir": errors.Unsupported, "removedir": errors.Unsupported},
    WorkspaceFilesystem: {},
}


class WriteGuardTableTest(unittest.TestCase):
    """The read-only guard is the same two flags on every branch, checked before any
    request is made. One table so that no mutating method can slip past it."""

    def check(self, fs, client, name, expected):
        with self.assertRaises(expected, msg=f"{type(fs).__name__}.{name}"):
            MUTATIONS[name](fs)
        self.assertEqual([], client.method_calls, f"{type(fs).__name__}.{name} touched the server")

    def test_read_only_by_default_refuses_every_mutation_without_a_request(self):
        for cls, not_offered in NOT_OFFERED.items():
            fs, client = branch_with_mock_client(cls, path_style="id")
            self.assertTrue(fs.getmeta()["read_only"])
            for name in MUTATIONS:
                self.check(fs, client, name, not_offered.get(name, errors.ResourceReadOnly))

    def test_writable_without_allow_delete_still_refuses_deletions(self):
        for cls, not_offered in NOT_OFFERED.items():
            fs, client = branch_with_mock_client(cls, path_style="id", writable=True)
            for name in DELETIONS:
                self.check(fs, client, name, not_offered.get(name, errors.ResourceReadOnly))
            try:
                MUTATIONS["upload"](fs)
            except errors.ResourceReadOnly:
                self.fail(f"{cls.__name__}: writable=True must let upload past the guard")
            except Exception:
                pass  # whatever the MagicMock client made of the request is not the point here

    def test_allow_delete_alone_lets_deletions_past_the_guard_but_not_writes(self):
        for cls, not_offered in NOT_OFFERED.items():
            fs, client = branch_with_mock_client(cls, path_style="id", allow_delete=True)
            self.check(fs, client, "upload", errors.ResourceReadOnly)
            self.check(fs, client, "move", errors.ResourceReadOnly)  # a move also writes
            for name in ("remove", "removedir"):
                if name in not_offered:
                    continue
                try:
                    MUTATIONS[name](fs)
                except errors.ResourceReadOnly:
                    self.fail(f"{cls.__name__}.{name}: allow_delete=True must get past the guard")
                except Exception:
                    pass


class LabelledPathStyleTest(unittest.TestCase):
    """The 'Name [GID]' path style: segments carry both, and resolve by the bracketed ID."""

    def test_the_default_style_is_plain_names(self):
        client = MagicMock()
        self.assertEqual("name", GalleryFilesystem(eln_client=client).path_style)
        self.assertEqual("labelled", GalleryFilesystem(eln_client=client, path_style="labelled").path_style)
        self.assertEqual("id", GalleryFilesystem(eln_client=client, path_style="id").path_style)
        with self.assertRaises(ValueError):
            GalleryFilesystem(eln_client=client, path_style="pretty")

    def test_gallery_listing_shows_names_and_resolves_by_id(self):
        fs, client = gallery_with_mock_client(path_style="labelled")
        self.assertEqual(["Images [GF10]", "a.png [GL100]"], fs.listdir("/"))
        infos = list(fs.scandir("/"))
        self.assertEqual("Images [GF10]", infos[0].name)
        # bare ids and labelled segments both resolve, and the info name is canonical
        self.assertEqual("Images [GF10]", fs.getinfo("/GF10").name)
        self.assertEqual("a.png [GL100]", fs.getinfo("/Images [GF10]/a.png [GL100]").name)
        client.get_file_info.assert_called_with("100")
        # a stale label still resolves because only the id is used
        self.assertEqual("a.png [GL100]", fs.getinfo("/Images [GF10]/old name [GL100]").name)

    def test_makedir_uses_the_plain_name_and_returns_a_labelled_path(self):
        fs, client = gallery_with_mock_client(path_style="labelled", writable=True)
        client.get_folder.return_value = {"id": 77, "globalId": "GF77", "name": "new"}
        fs.makedir("/Images [GF10]/new")
        client.create_folder.assert_called_once_with("new", "10")
        with self.assertRaises(errors.InvalidPath):
            fs.makedir("/Images [GF10]/GF999")

    def test_inventory_labelled_upload_passes_bare_global_id(self):
        fs, client = inventory_with_mock_client(path_style="labelled", writable=True)
        self.assertEqual(["map.gb [IF5]"], fs.listdir("/Freezer [IC1]"))
        self.assertEqual("Freezer [IC1]", fs.getinfo("/IC1").name)
        payload = BytesIO(b"x")
        fs.upload("/Freezer [IC1]/x.txt", payload)
        client.upload_attachment_by_global_id.assert_called_once_with("IC1", payload, filename="x.txt")


class ClassifyMediaSectionTest(unittest.TestCase):

    def test_extension_picks_the_section_and_documents_is_not_a_catch_all(self):
        from rspace_client.fs.gallery import classify_media_section
        self.assertEqual("Images", classify_media_section("photo.png"))
        self.assertEqual("Images", classify_media_section("photo.JPG"))
        self.assertEqual("Audios", classify_media_section("song.mp3"))
        self.assertEqual("Videos", classify_media_section("clip.mp4"))
        self.assertEqual("Documents", classify_media_section("report.pdf"))
        self.assertEqual("Documents", classify_media_section("notes.md"))
        self.assertEqual("Chemistry", classify_media_section("reaction.cdxml"))
        # unlisted extensions and types with no specialised section fall through to Miscellaneous
        for name in ("data.xyz", "archive.zip", "movie.mkv"):
            self.assertEqual("Miscellaneous", classify_media_section(name), name)
        self.assertIsNone(classify_media_section("noextension"))
        self.assertIsNone(classify_media_section(None))


class MismatchMessageTest(unittest.TestCase):
    """
    The section-mismatch message reaches end users verbatim (Galaxy shows it in the browser),
    so it must lead with something a person can act on rather than a Python argument.
    """

    def _message(self, filename, folder_section, guessed_section_name):
        from rspace_client.client_base import ClientBase
        from rspace_client.fs.gallery import GalleryFilesystem, GallerySectionMismatch
        client = MagicMock()
        client.upload_file.side_effect = ClientBase.ApiError("File type not allowed", response_status_code=400)
        client.get_folder.return_value = {"id": 8, "globalId": "GF8", "mediaType": folder_section}
        fs = GalleryFilesystem(eln_client=client, writable=True, path_style="id")
        payload = BytesIO(b"x")
        payload.name = filename
        with self.assertRaises(GallerySectionMismatch) as ctx:
            fs.upload("/GF8/" + payload.name, payload)
        return str(ctx.exception)

    def test_message_tells_a_person_what_to_do(self):
        message = self._message("exported.csv", "Images", "Documents")
        self.assertIn("Choose a folder in the 'Documents' section instead", message)
        self.assertIn("upload without choosing a folder", message)
        self.assertNotIn("construct the filesystem", message)
        self.assertIn("exported.csv", message)
        self.assertIn("Images", message)
        self.assertIn("File type not allowed", message)  # the server's own reason survives

    def test_api_hint_is_kept_for_library_callers(self):
        self.assertIn("on_mismatch='reroute'", self._message("exported.csv", "Images", "Documents"))

    def test_the_exception_chain_is_suppressed(self):
        """Galaxy prints the whole chain and clips it from the top, so three stacked
        tracebacks would hide the explanation. One traceback, message last."""
        import traceback
        from rspace_client.client_base import ClientBase
        from rspace_client.fs.gallery import GalleryFilesystem, GallerySectionMismatch
        client = MagicMock()
        client.upload_file.side_effect = ClientBase.ApiError("File type not allowed", response_status_code=422)
        client.get_folder.return_value = {"id": 8, "globalId": "GF8", "mediaType": "Images"}
        fs = GalleryFilesystem(eln_client=client, writable=True, path_style="id")
        payload = BytesIO(b"x")
        payload.name = "notes.csv"
        try:
            fs.upload("/GF8/" + payload.name, payload)
        except GallerySectionMismatch as err:
            self.assertIsNone(err.__cause__)
            self.assertTrue(err.__suppress_context__)
            rendered = "".join(traceback.format_exception(type(err), err, err.__traceback__))
            self.assertEqual(1, rendered.count("Traceback (most recent call last)"))
            self.assertIn("File type not allowed", rendered)  # server reason still reported
            self.assertTrue(rendered.strip().endswith(str(err)))
        else:
            self.fail("expected GallerySectionMismatch")

    def test_article_agrees_with_the_section_name(self):
        self.assertIn("an 'Images' file", self._message("photo.jpg", "Documents", "Images"))
        self.assertIn("a 'Documents' file", self._message("notes.csv", "Images", "Documents"))

    def test_unclassifiable_file_points_at_miscellaneous(self):
        self.assertIn("'Miscellaneous' section", self._message("archive.zip", "Images", "Miscellaneous"))


class ApiErrorTranslationTest(unittest.TestCase):
    """RSpace client exceptions surface as fs.errors at every public method."""

    def test_404_is_resource_not_found_and_exists_is_false(self):
        fs, client = gallery_with_mock_client()
        client.get_folder.side_effect = ClientBase.ApiError("gone", response_status_code=404)
        with self.assertRaises(errors.ResourceNotFound):
            fs.getinfo("/GF10")
        self.assertFalse(fs.exists("/GF10"))
        self.assertFalse(fs.isdir("/GF10"))

    def test_403_and_401_are_permission_denied(self):
        fs, client = gallery_with_mock_client()
        client.get_folder.side_effect = ClientBase.ApiError("no", response_status_code=403)
        with self.assertRaises(errors.PermissionDenied):
            fs.getinfo("/GF10")
        from rspace_client.exceptions import AuthenticationError
        client.get_folder.side_effect = AuthenticationError("bad key")
        with self.assertRaises(errors.PermissionDenied):
            fs.getinfo("/GF10")

    def test_5xx_and_connection_failures_are_remote_connection_errors(self):
        fs, client = gallery_with_mock_client()
        client.get_folder.side_effect = ClientBase.ApiError("boom", response_status_code=503)
        with self.assertRaises(errors.RemoteConnectionError):
            fs.getinfo("/GF10")
        from rspace_client.exceptions import RSpaceConnectionError
        client.get_folder.side_effect = RSpaceConnectionError("refused")
        with self.assertRaises(errors.RemoteConnectionError):
            fs.getinfo("/GF10")

    def test_domain_errors_keep_the_api_exception(self):
        # 400/409/422 carry the server's own explanation (a refused link, a wrong section)
        fs, client = gallery_with_mock_client()
        client.get_folder.side_effect = ClientBase.ApiError("nope", response_status_code=422)
        with self.assertRaises(ClientBase.ApiError):
            fs.getinfo("/GF10")

    def test_errors_during_a_lazy_listing_are_translated_too(self):
        fs, client = gallery_with_mock_client()
        client.list_folder_tree.side_effect = lambda *a, **kw: {
            "records": [{"id": 2, "globalId": "FL2", "name": "Gallery"}],
            "_links": [{"rel": "next", "link": "http://example.com/api/v1/folders/tree?pageNumber=1"}]}
        client.get_link_contents.side_effect = ClientBase.ApiError("gone", response_status_code=404)
        listing = fs.scandir("/")  # first page is fine; the second page fails while iterating
        with self.assertRaises(errors.ResourceNotFound):
            list(listing)

    def test_the_original_exception_is_kept_as_the_cause(self):
        fs, client = gallery_with_mock_client()
        original = ClientBase.ApiError("gone", response_status_code=404)
        client.get_folder.side_effect = original
        with self.assertRaises(errors.ResourceNotFound) as ctx:
            fs.getinfo("/GF10")
        self.assertIs(original, ctx.exception.__cause__)
        self.assertIs(original, ctx.exception.exc)


if __name__ == "__main__":
    unittest.main()
