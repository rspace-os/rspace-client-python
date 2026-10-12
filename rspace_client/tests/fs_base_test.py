"""
Unit tests for the shared fsspec base (rspace_client.fs.base) and the Gallery and
Inventory branches built on it. No network: the RSpace clients are replaced with
MagicMocks.

Paths are fsspec paths: no leading slash, the root is "". Entries are plain dicts whose
``name`` is the full path, so a child's own segment is ``paths.last_segment(entry["name"])``.
"""
import errno
import traceback
import unittest
from datetime import datetime, timezone
from io import BytesIO
from unittest.mock import MagicMock

from rspace_client.client_base import ClientBase
from rspace_client.exceptions import AuthenticationError, RSpaceConnectionError
from rspace_client.fs import (GalleryFilesystem, GallerySectionMismatch, InventoryFilesystem,
                              ReadOnlyError, RemoteApiError, WorkspaceFilesystem, make_entry)
from rspace_client.fs.base import to_epoch
from rspace_client.fs.gallery import classify_media_section
from rspace_client.tests.mock_server_case import segments




class MakeEntryTest(unittest.TestCase):

    def test_iso_and_millis_timestamps_become_epoch_seconds(self):
        self.assertAlmostEqual(to_epoch("2026-09-01T09:00:00.000Z"), 1788253200.0)
        self.assertAlmostEqual(to_epoch(1788253200000), 1788253200.0)
        self.assertIsNone(to_epoch(None))
        self.assertIsNone(to_epoch("not a date"))

    def test_details_and_rspace_keys(self):
        entry = make_entry("GL5", False, raw={"globalId": "GL5", "name": "data.csv"}, size=27,
                           created="2026-09-01T09:00:00.000Z", modified="2026-09-02T09:00:00.000Z")
        self.assertEqual("GL5", entry["name"])
        self.assertEqual("file", entry["type"])
        self.assertEqual(27, entry["size"])
        created = datetime.fromtimestamp(entry["created"], tz=timezone.utc)
        self.assertEqual(2026, created.year)
        modified = datetime.fromtimestamp(entry["mtime"], tz=timezone.utc)
        self.assertEqual(2, modified.day)
        self.assertEqual("data.csv", entry["rspace"]["name"])
        self.assertEqual("GL5", entry["globalId"])
        self.assertNotIn("writable", entry)  # unknown, not guessed

    def test_mtime_falls_back_to_created(self):
        entry = make_entry("GL5", False, created="2026-09-01T09:00:00.000Z")
        self.assertEqual(entry["created"], entry["mtime"])

    def test_directory_entry(self):
        entry = make_entry("GF1", True)
        self.assertEqual("directory", entry["type"])
        self.assertIsNone(entry["size"])
        self.assertIsNone(entry["created"])
        self.assertIsNone(entry["mtime"])

    def test_writable_is_only_set_when_known(self):
        self.assertFalse(make_entry("SD1", True, writable=False)["writable"])
        self.assertTrue(make_entry("SD1", True, writable=True)["writable"])


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
    client.get_folder.return_value = {"id": 10, "globalId": "GF10", "name": "Images"}
    client.get_file_info.return_value = {"id": 100, "globalId": "GL100", "name": "a.png", "size": 5}
    client.create_folder.return_value = {"id": 77, "globalId": "GF77", "name": "new"}
    kwargs.setdefault("path_style", "id")
    return GalleryFilesystem(eln_client=client, **kwargs), client


class GalleryFilesystemTest(unittest.TestCase):

    def test_root_is_resolved_lazily(self):
        fs, client = gallery_with_mock_client()
        client.list_folder_tree.assert_not_called()  # no network in the constructor
        self.assertEqual(["GF10", "GL100"], fs.ls("", detail=False))
        self.assertEqual(2, fs.gallery_id)

    def test_missing_gallery_folder_is_a_clear_error(self):
        client = MagicMock()
        client.list_folder_tree.return_value = {"records": [{"id": 1, "name": "Something else"}]}
        with self.assertRaises(FileNotFoundError):
            GalleryFilesystem(eln_client=client).ls("")

    def test_sizes_are_topped_up_when_the_listing_omits_them(self):
        """Real folder-tree items have no size; consumers such as Galaxy require an int.
        ``fetch_sizes`` decides whether a listing pays one request per file for it."""
        listing = {"records": [{"id": 100, "globalId": "GL100", "name": "a.png",
                                "created": "2026-09-01T09:02:00.000Z"}]}  # no 'size'
        fs, client = gallery_with_mock_client(fetch_sizes=False)
        client.list_folder_tree.side_effect = None
        client.list_folder_tree.return_value = listing
        fs._gallery_id = 2
        self.assertIsNone(next(iter(fs.scandir("")))["size"])  # one call, no size
        client.get_file_info.assert_not_called()

        fs, client = gallery_with_mock_client()  # fetch_sizes=True is the default
        client.list_folder_tree.side_effect = None
        client.list_folder_tree.return_value = listing
        fs._gallery_id = 2
        entry = next(iter(fs.scandir("")))
        client.get_file_info.assert_called_once_with(100)
        self.assertEqual(5, entry["size"])

    def test_scandir_uses_one_listing_call_and_carries_details(self):
        fs, client = gallery_with_mock_client()
        entries = list(fs.scandir(""))
        self.assertEqual(["GF10", "GL100"], [e["name"] for e in entries])
        self.assertEqual(["directory", "file"], [e["type"] for e in entries])
        self.assertEqual(5, entries[1]["size"])
        self.assertIsNotNone(entries[1]["created"])
        self.assertEqual("a.png", entries[1]["rspace"]["name"])
        self.assertEqual("GL100", entries[1]["globalId"])
        client.get_folder.assert_not_called()  # no per-child info
        client.get_file_info.assert_not_called()  # the listing already carried a size

    def test_ls_names_are_full_paths(self):
        fs, _ = gallery_with_mock_client()
        client_listing = fs.ls("GF10", detail=False)
        self.assertEqual([], client_listing)
        root = fs.ls("", detail=True)
        self.assertEqual(["GF10", "GL100"], [e["name"] for e in root])
        self.assertEqual(["GF10", "GL100"], segments(root))

    def test_info_root_and_children(self):
        fs, _ = gallery_with_mock_client()
        self.assertEqual("directory", fs.info("")["type"])
        self.assertEqual("GF10", fs.info("GF10")["name"])
        entry = fs.info("GF10/GL100")
        self.assertEqual("GF10/GL100", entry["name"])  # info names the path it was asked about
        self.assertEqual("file", entry["type"])
        self.assertEqual("GL100", entry["globalId"])
        with self.assertRaises(FileNotFoundError):
            fs.info("XX1")

    def test_created_and_modified_are_datetimes(self):
        fs, client = gallery_with_mock_client()
        client.get_file_info.return_value = {"id": 100, "globalId": "GL100", "name": "a.png", "size": 5,
                                             "created": "2026-09-01T09:02:00.000Z"}
        created = fs.created("GF10/GL100")
        self.assertEqual(2026, created.astimezone(timezone.utc).year)
        self.assertEqual(created, fs.modified("GF10/GL100"))  # no lastModified: created stands in
        self.assertIsNone(fs.created(""))

    def test_writable_allows_upload_and_mkdir(self):
        fs, client = gallery_with_mock_client(writable=True)
        self.assertFalse(fs.read_only)
        payload = BytesIO(b"x")
        fs.upload_fileobj("GF10/x.png", payload)
        client.upload_file.assert_called_once_with(payload, "10", filename="x.png")
        fs.upload_fileobj("x.png", payload)  # directly under the root -> API default folder
        client.upload_file.assert_called_with(payload, None, filename="x.png")
        self.assertIsNone(fs.mkdir("GF10/new"))
        client.create_folder.assert_called_once_with("new", "10")

    def test_mkdir_at_root_targets_gallery_root(self):
        fs, client = gallery_with_mock_client(writable=True)
        fs.mkdir("new")
        client.create_folder.assert_called_once_with("new", 2)

    def test_mkdir_refuses_an_existing_folder_unless_exist_ok(self):
        fs, client = gallery_with_mock_client(writable=True)
        with self.assertRaises(FileExistsError):
            fs.mkdir("Images")
        client.create_folder.assert_not_called()
        fs.mkdir("Images", exist_ok=True)
        fs.makedirs("GF10", exist_ok=True)
        client.create_folder.assert_not_called()

    def test_rmdir_reaches_the_client_but_never_for_the_root(self):
        fs, client = gallery_with_mock_client(allow_delete=True)
        fs.rmdir("GF10")
        client.delete_folder.assert_called_once_with("10")
        with self.assertRaises(PermissionError):
            fs.rmdir("")
        client.delete_folder.assert_called_once()

    def test_rmdir_refuses_a_folder_that_is_not_empty(self):
        fs, client = gallery_with_mock_client(allow_delete=True)
        client.list_folder_tree.side_effect = None
        client.list_folder_tree.return_value = {"records": [{"id": 100, "globalId": "GL100", "name": "a.png", "size": 5}]}
        fs._gallery_id = 2
        with self.assertRaises(OSError) as ctx:
            fs.rmdir("GF10")
        self.assertEqual(errno.ENOTEMPTY, ctx.exception.errno)
        client.delete_folder.assert_not_called()

    def test_open_read_downloads(self):
        fs, client = gallery_with_mock_client()
        client.download_file.side_effect = lambda fid, fh, chunk_size=128: fh.write(b"bytes")
        with fs.open("GF10/GL100", "rb") as fh:
            self.assertEqual(b"bytes", fh.read())
        client.download_file.assert_called_once()
        self.assertEqual("100", client.download_file.call_args[0][0])
        self.assertEqual(b"bytes", fs.cat_file("GF10/GL100"))
        buffer = BytesIO()
        fs.download_fileobj("GF10/GL100", buffer)
        self.assertEqual(b"bytes", buffer.getvalue())

    def test_opening_a_directory_for_reading_is_refused(self):
        fs, _ = gallery_with_mock_client()
        with self.assertRaises(IsADirectoryError):
            fs.cat_file("GF10")

    def test_open_write_uploads_on_close(self):
        fs, client = gallery_with_mock_client(writable=True)
        with fs.open("GF10/x.png", "wb") as fh:
            fh.write(b"abc")
            client.upload_file.assert_not_called()  # buffered: one request per upload
        client.upload_file.assert_called_once()
        sent, folder_id = client.upload_file.call_args[0]
        self.assertEqual(b"abc", sent.read())
        self.assertEqual("10", folder_id)
        self.assertEqual({"filename": "x.png"}, client.upload_file.call_args[1])

    def test_a_transaction_defers_the_upload_and_discards_it_on_error(self):
        fs, client = gallery_with_mock_client(writable=True)
        with fs.transaction:
            with fs.open("GF10/x.png", "wb") as fh:
                fh.write(b"abc")
            client.upload_file.assert_not_called()  # the file was closed, nothing was sent yet
        client.upload_file.assert_called_once()
        self.assertEqual(b"abc", client.upload_file.call_args[0][0].read())

        fs, client = gallery_with_mock_client(writable=True)
        with self.assertRaises(RuntimeError):
            with fs.transaction:
                with fs.open("GF10/y.png", "wb") as fh:
                    fh.write(b"never")
                raise RuntimeError("abort")
        client.upload_file.assert_not_called()

    def test_glob_finds_a_bracketed_segment_in_listing_order(self):
        """Galaxy's search box escapes '[' as '\\[' and hands the pattern to glob; fsspec's own
        glob would read '[GL112]' as a character class and find nothing."""
        fs, client = gallery_with_mock_client(path_style="name")
        client.list_folder_tree.side_effect = lambda folder_id=None, **kw: {
            None: {"records": [{"id": 2, "globalId": "FL2", "name": "Gallery"}]},
            2: {"records": [{"id": 11, "globalId": "GF11", "name": "Documents"}]},
            "11": {"records": [{"id": 110, "globalId": "GL110", "name": "protocol.docx", "size": 1},
                               {"id": 111, "globalId": "GL111", "name": "data.csv", "size": 1},
                               {"id": 112, "globalId": "GL112", "name": "data.csv", "size": 1}]},
        }[folder_id]
        self.assertEqual(["Documents/data [GL112].csv"], fs.glob("Documents/*\\[GL112\\]*"))
        self.assertEqual(["Documents/data.csv", "Documents/data [GL112].csv"], fs.glob("Documents/*data*"))
        self.assertEqual(["Documents/data.csv", "Documents/data [GL112].csv"], fs.glob("Documents/*DATA*"))
        found = fs.glob("Documents/*.csv*", detail=True)
        self.assertEqual("GL111", found["Documents/data.csv"]["globalId"])
        self.assertEqual([], fs.glob("Documents/*nothing*"))


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

    def test_entry_names_are_full_paths_and_the_segment_is_the_record(self):
        fs, _ = inventory_with_mock_client()
        self.assertEqual("IC1/IF5", fs.info("IC1/IF5")["name"])  # info names the path asked for
        self.assertEqual("IF5", fs.info("IF5")["name"])
        self.assertEqual("map.gb", fs.info("IC1/IF5")["rspace"]["name"])
        entries = fs.ls("IC1")
        self.assertEqual(["IC1/IF5"], [e["name"] for e in entries])
        self.assertEqual(["IF5"], segments(entries))

    def test_record_is_a_directory(self):
        fs, client = inventory_with_mock_client()
        entry = fs.info("IC1")
        # info describes the record itself, so it does not pay for the container's contents
        client.get_container_by_id.assert_called_with("1")
        self.assertEqual("directory", entry["type"])
        self.assertEqual("IC1", entry["name"])
        self.assertEqual("Freezer", entry["rspace"]["name"])

    def test_listing_a_container_asks_for_its_contents(self):
        fs, client = inventory_with_mock_client()
        list(fs.scandir("IC1"))
        client.get_container_by_id.assert_called_with("1", include_content=True)

    def test_scandir_builds_children_from_the_record(self):
        fs, client = inventory_with_mock_client()
        entries = list(fs.scandir("IC1"))
        self.assertEqual(["IF5"], segments(entries))  # container with no content: attachments only
        self.assertEqual(9, entries[0]["size"])
        self.assertIsNotNone(entries[0]["created"])
        self.assertEqual("file", entries[0]["type"])
        client.get_attachment_by_id.assert_not_called()
        self.assertEqual(["IC1/IF5"], fs.ls("IC1", detail=False))

    def test_root_lists_benches_and_sections(self):
        fs, client = inventory_with_mock_client()
        client.get_workbenches.return_value = [{"id": 1, "globalId": "BE1", "name": "WB me", "cType": "WORKBENCH"}]
        self.assertEqual(["BE1", "Containers", "Samples", "Templates"], fs.ls("", detail=False))
        self.assertEqual("directory", fs.info("")["type"])
        self.assertEqual("directory", fs.info("Containers")["type"])
        client.get_container_by_id.assert_not_called()

    def test_upload_and_remove_reach_the_client(self):
        fs, client = inventory_with_mock_client(writable=True, allow_delete=True)
        payload = BytesIO(b"x")
        fs.upload_fileobj("IC1/x.txt", payload)
        client.upload_attachment_by_global_id.assert_called_once_with("IC1", payload, filename="x.txt")
        fs.rm_file("IC1/IF5")
        client.delete_attachment_by_id.assert_called_once_with("5")

    def test_rm_also_removes_a_file(self):
        fs, client = inventory_with_mock_client(allow_delete=True)
        fs.rm("IC1/IF5")
        client.delete_attachment_by_id.assert_called_once_with("5")
        with self.assertRaises(NotImplementedError):
            fs.rm("IC1", recursive=True)


def branch_with_mock_client(cls, **posture):
    client = MagicMock()
    fs = cls(inv_client=client, **posture) if cls is InventoryFilesystem else cls(eln_client=client, **posture)
    return fs, client


#: every way of changing the server that a branch filesystem offers
MUTATIONS = {
    "upload_fileobj": lambda f: f.upload_fileobj("GF10/x.txt", BytesIO(b"x")),
    "mkdir": lambda f: f.mkdir("GF10/new"),
    "rmdir": lambda f: f.rmdir("GF10"),
    "rm_file": lambda f: f.rm_file("GF10/GL1"),
    "link": lambda f: f.link("GF10", "GL1"),
    "open 'wb'": lambda f: f.open("GF10/GL1", "wb"),
    "pipe_file": lambda f: f.pipe_file("GF10/x.txt", b"x"),
    "cp_file": lambda f: f.cp_file("GF10/GL1", "GF10/GL2"),
    "mv": lambda f: f.mv("GF10/GL1", "GF10/GL2"),
}
DELETIONS = ("rm_file", "rmdir", "mv")

#: what a branch does not offer at all is refused the same way however it was opened
NOT_OFFERED = {
    GalleryFilesystem: {"rm_file": NotImplementedError,  # the RSpace API cannot delete Gallery files
                        "link": NotImplementedError},    # a Gallery file is already in the Gallery
    InventoryFilesystem: {"mkdir": NotImplementedError, "rmdir": NotImplementedError},
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
            self.assertTrue(fs.read_only)
            for name in MUTATIONS:
                self.check(fs, client, name, not_offered.get(name, ReadOnlyError))

    def test_read_only_error_is_a_permission_error(self):
        fs, _ = branch_with_mock_client(GalleryFilesystem, path_style="id")
        with self.assertRaises(PermissionError) as ctx:
            fs.mkdir("GF10/new")
        self.assertEqual(errno.EROFS, ctx.exception.errno)

    def test_writable_without_allow_delete_still_refuses_deletions(self):
        for cls, not_offered in NOT_OFFERED.items():
            fs, client = branch_with_mock_client(cls, path_style="id", writable=True)
            for name in DELETIONS:
                self.check(fs, client, name, not_offered.get(name, ReadOnlyError))
            try:
                MUTATIONS["upload_fileobj"](fs)
            except ReadOnlyError:
                self.fail(f"{cls.__name__}: writable=True must let upload past the guard")
            except Exception:
                pass  # whatever the MagicMock client made of the request is not the point here

    def test_allow_delete_alone_lets_deletions_past_the_guard_but_not_writes(self):
        for cls, not_offered in NOT_OFFERED.items():
            fs, client = branch_with_mock_client(cls, path_style="id", allow_delete=True)
            self.check(fs, client, "upload_fileobj", ReadOnlyError)
            self.check(fs, client, "mv", ReadOnlyError)  # a move also writes
            for name in ("rm_file", "rmdir"):
                if name in not_offered:
                    continue
                try:
                    MUTATIONS[name](fs)
                except ReadOnlyError:
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
        self.assertEqual(["Images [GF10]", "a.png [GL100]"], fs.ls("", detail=False))
        entries = list(fs.scandir(""))
        self.assertEqual("Images [GF10]", entries[0]["name"])
        # bare ids and labelled segments both resolve to the same record
        self.assertEqual("GF10", fs.info("GF10")["globalId"])
        entry = fs.info("Images [GF10]/a.png [GL100]")
        self.assertEqual("GL100", entry["globalId"])
        self.assertEqual("a.png", entry["rspace"]["name"])
        client.get_file_info.assert_called_with("100")
        # a stale label still resolves because only the id is used
        self.assertEqual("GL100", fs.info("Images [GF10]/old name [GL100]")["globalId"])

    def test_mkdir_uses_the_plain_name(self):
        fs, client = gallery_with_mock_client(path_style="labelled", writable=True)
        client.get_folder.return_value = {"id": 77, "globalId": "GF77", "name": "new"}
        fs.mkdir("Images [GF10]/new")
        client.create_folder.assert_called_once_with("new", "10")
        with self.assertRaises(ValueError):
            fs.mkdir("Images [GF10]/GF999")

    def test_inventory_labelled_upload_passes_bare_global_id(self):
        fs, client = inventory_with_mock_client(path_style="labelled", writable=True)
        self.assertEqual(["Freezer [IC1]/map.gb [IF5]"], fs.ls("Freezer [IC1]", detail=False))
        self.assertEqual("Freezer", fs.info("IC1")["rspace"]["name"])
        payload = BytesIO(b"x")
        fs.upload_fileobj("Freezer [IC1]/x.txt", payload)
        client.upload_attachment_by_global_id.assert_called_once_with("IC1", payload, filename="x.txt")


class ClassifyMediaSectionTest(unittest.TestCase):

    def test_extension_picks_the_section_and_documents_is_not_a_catch_all(self):
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
        client = MagicMock()
        client.upload_file.side_effect = ClientBase.ApiError("File type not allowed", response_status_code=400)
        client.get_folder.return_value = {"id": 8, "globalId": "GF8", "mediaType": folder_section}
        fs = GalleryFilesystem(eln_client=client, writable=True, path_style="id")
        payload = BytesIO(b"x")
        payload.name = filename
        with self.assertRaises(GallerySectionMismatch) as ctx:
            fs.upload_fileobj("GF8/" + payload.name, payload)
        self.assertEqual(folder_section, ctx.exception.folder_section)
        self.assertEqual("GF8", ctx.exception.folder_global_id)
        self.assertEqual(guessed_section_name, ctx.exception.file_media_type)
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
        client = MagicMock()
        client.upload_file.side_effect = ClientBase.ApiError("File type not allowed", response_status_code=422)
        client.get_folder.return_value = {"id": 8, "globalId": "GF8", "mediaType": "Images"}
        fs = GalleryFilesystem(eln_client=client, writable=True, path_style="id")
        payload = BytesIO(b"x")
        payload.name = "notes.csv"
        try:
            fs.upload_fileobj("GF8/" + payload.name, payload)
        except GallerySectionMismatch as err:
            self.assertIsNone(err.__cause__)
            self.assertTrue(err.__suppress_context__)
            rendered = "".join(traceback.format_exception(type(err), err, err.__traceback__))
            self.assertEqual(1, rendered.count("Traceback (most recent call last)"))
            self.assertIn("File type not allowed", rendered)  # server reason still reported
            self.assertTrue(rendered.strip().endswith(str(err)))
        else:
            self.fail("expected GallerySectionMismatch")

    def test_the_mismatch_is_not_turned_into_an_os_error(self):
        """It is an ApiError subclass with fs_passthrough: the error translation leaves it alone."""
        self.assertTrue(GallerySectionMismatch.fs_passthrough)
        self.assertTrue(issubclass(GallerySectionMismatch, ClientBase.ApiError))
        self.assertFalse(issubclass(GallerySectionMismatch, OSError))

    def test_reroute_places_the_file_in_the_default_folder(self):
        client = MagicMock()
        client.upload_file.side_effect = [
            ClientBase.ApiError("File type not allowed", response_status_code=400),
            {"id": 999, "globalId": "GL999", "name": "notes.csv", "parentFolderId": 14},
        ]
        client.get_folder.side_effect = lambda fid: (
            {"id": 8, "globalId": "GF8", "mediaType": "Images"} if str(fid) == "8"
            else {"id": 14, "globalId": "GF14", "mediaType": "Documents", "name": "Api Inbox"})
        fs = GalleryFilesystem(eln_client=client, writable=True, path_style="id", on_mismatch="reroute")
        placement = fs.upload_fileobj("GF8/notes.csv", BytesIO(b"x"))
        self.assertTrue(placement.rerouted)
        self.assertEqual("GL999", placement.file_global_id)
        self.assertEqual("GF14", placement.folder_global_id)
        self.assertEqual("Documents", placement.section)
        self.assertEqual("GF8", placement.requested_path)
        self.assertEqual(2, client.upload_file.call_count)
        self.assertIsNone(client.upload_file.call_args[0][1])  # the retry names no folder

    def test_article_agrees_with_the_section_name(self):
        self.assertIn("an 'Images' file", self._message("photo.jpg", "Documents", "Images"))
        self.assertIn("a 'Documents' file", self._message("notes.csv", "Images", "Documents"))

    def test_unclassifiable_file_points_at_miscellaneous(self):
        self.assertIn("'Miscellaneous' section", self._message("archive.zip", "Images", "Miscellaneous"))


class ApiErrorTranslationTest(unittest.TestCase):
    """RSpace client exceptions surface as OSError subclasses at every public method."""

    def test_404_is_file_not_found_and_exists_is_false(self):
        fs, client = gallery_with_mock_client()
        client.get_folder.side_effect = ClientBase.ApiError("gone", response_status_code=404)
        with self.assertRaises(FileNotFoundError):
            fs.info("GF10")
        self.assertFalse(fs.exists("GF10"))
        self.assertFalse(fs.isdir("GF10"))
        self.assertFalse(fs.isfile("GF10"))

    def test_403_and_401_are_permission_errors(self):
        fs, client = gallery_with_mock_client()
        client.get_folder.side_effect = ClientBase.ApiError("no", response_status_code=403)
        with self.assertRaises(PermissionError):
            fs.info("GF10")
        client.get_folder.side_effect = ClientBase.ApiError("no", response_status_code=401)
        with self.assertRaises(PermissionError):
            fs.info("GF10")
        client.get_folder.side_effect = AuthenticationError("bad key")
        with self.assertRaises(PermissionError):
            fs.info("GF10")

    def test_5xx_and_connection_failures_are_connection_errors(self):
        fs, client = gallery_with_mock_client()
        client.get_folder.side_effect = ClientBase.ApiError("boom", response_status_code=503)
        with self.assertRaises(ConnectionError):
            fs.info("GF10")
        client.get_folder.side_effect = RSpaceConnectionError("refused")
        with self.assertRaises(ConnectionError):
            fs.info("GF10")

    def test_domain_errors_become_remote_api_errors_carrying_the_api_exception(self):
        # 400/409/422 carry the server's own explanation (a refused link, a wrong section)
        fs, client = gallery_with_mock_client()
        for status in (400, 409, 422):
            original = ClientBase.ApiError("nope", response_status_code=status)
            client.get_folder.side_effect = original
            with self.assertRaises(RemoteApiError) as ctx:
                fs.info("GF10")
            self.assertIsInstance(ctx.exception, OSError)
            self.assertIs(original, ctx.exception.api_error)
            self.assertEqual(status, ctx.exception.status)
            self.assertIn("nope", str(ctx.exception))

    def test_errors_during_a_lazy_listing_are_translated_too(self):
        fs, client = gallery_with_mock_client()
        client.list_folder_tree.side_effect = lambda *a, **kw: {
            "records": [{"id": 2, "globalId": "FL2", "name": "Gallery"}],
            "_links": [{"rel": "next", "link": "http://example.com/api/v1/folders/tree?pageNumber=1"}]}
        client.get_link_contents.side_effect = ClientBase.ApiError("gone", response_status_code=404)
        listing = fs.scandir("")  # first page is fine; the second page fails while iterating
        with self.assertRaises(FileNotFoundError):
            list(listing)

    def test_errors_in_ls_and_file_reads_are_translated(self):
        fs, client = gallery_with_mock_client()
        client.list_folder_tree.side_effect = ClientBase.ApiError("gone", response_status_code=404)
        with self.assertRaises(FileNotFoundError):
            fs.ls("")
        fs, client = gallery_with_mock_client()
        client.download_file.side_effect = ClientBase.ApiError("no", response_status_code=403)
        with self.assertRaises(PermissionError):
            fs.cat_file("GF10/GL100")
        with self.assertRaises(PermissionError):
            fs.open("GF10/GL100", "rb")

    def test_the_original_exception_is_kept_as_the_cause(self):
        fs, client = gallery_with_mock_client()
        original = ClientBase.ApiError("gone", response_status_code=404)
        client.get_folder.side_effect = original
        with self.assertRaises(FileNotFoundError) as ctx:
            fs.info("GF10")
        self.assertIs(original, ctx.exception.__cause__)


if __name__ == "__main__":
    unittest.main()
