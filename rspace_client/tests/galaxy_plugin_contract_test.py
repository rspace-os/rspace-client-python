"""
The contract Galaxy's shipped RSpace file source relies on.

Galaxy has shipped ``galaxy/files/sources/rspace.py`` since 25.1. It is built on
``rspace_client.eln.fs.GalleryFilesystem``, and it does not merely call it: it subclasses
it, monkeypatches ``ELNClient.upload_file`` with a function of its own, and hands that
function a ``FakedNameIO`` wrapper that forwards ``read`` through ``__getattr__``. Anything this
library does to those call shapes reaches Galaxy users as a broken upload button, so the
shapes Galaxy depends on are pinned here.

The classes below are copied from Galaxy's plugin rather than imported, so that the test
runs without Galaxy installed and keeps working when Galaxy is not on the path. Keep them
in step with `galaxy/files/sources/rspace.py` when that file changes.
"""
import os
import unittest
import warnings
from io import BytesIO
from types import MethodType

from .mock_server_case import MockServerTestCase


class FakedNameIO:
    """Galaxy wraps the dataset it uploads so the name carries a real extension: its own
    datasets are all called *.dat, which the Gallery would reject outside Miscellaneous."""

    def __init__(self, handle, name=None):
        self._handle = handle
        self._name = name

    @property
    def name(self):
        return self._name or self._handle.name

    def __getattr__(self, attribute):
        return getattr(self._handle, attribute)


class GalleryFilesystemContractTest(MockServerTestCase):

    def galaxy_style_filesystem(self):
        """Build the filesystem the way Galaxy's plugin builds it, patches and all."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")  # the shim's DeprecationWarning is expected
            from rspace_client.eln.fs import GalleryFilesystem

        test = self

        class Patched(GalleryFilesystem):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                original = self.eln_client.upload_file

                # Galaxy replaces upload_file with exactly this signature: no **kwargs, and
                # no 'filename'. A new keyword argument here is a TypeError in production.
                def upload_file(self_, file, folder_id=None, caption=None):
                    self._upload_response = original(file, folder_id=folder_id, caption=caption)
                    test.patched_call = {"name": getattr(file, "name", None), "folder_id": folder_id}

                self.eln_client.upload_file = MethodType(upload_file, self.eln_client)

            def upload(self, path, file, chunk_size=None, **options):
                super().upload(path, file, chunk_size, **options)
                self.upload_global_id = self._upload_response["globalId"]

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            fs = Patched(self.url, "k")
        inner = fs.upload

        def upload(self_, path, file, chunk_size=None, **options):
            # Galaxy passes the *containing folder* as the path and names the file through
            # the wrapper, which is the convention the deprecated shim still honours.
            inner(os.path.dirname(path), FakedNameIO(file, name=os.path.basename(path)), chunk_size, **options)

        fs.upload = MethodType(upload, fs)
        return fs

    def test_galaxy_can_still_upload(self):
        fs = self.galaxy_style_filesystem()
        fs.upload("/GF11/report.csv", BytesIO(b"a,b\n1,2\n"))
        self.assertTrue(fs.upload_global_id.startswith("GL"))
        # the name reached the API through the file object, not through a new keyword
        self.assertEqual({"name": "report.csv", "folder_id": "11"}, self.patched_call)
        self.assertIn(fs.upload_global_id, fs.listdir("/GF11"))

    def test_galaxy_reads_names_dates_and_sizes_out_of_the_info(self):
        """Galaxy's _resource_info_to_dict takes the segment from 'basic', the display name
        and an ISO created date from 'rspace', and requires an integer size."""
        import datetime
        fs = self.galaxy_style_filesystem()
        rows = list(fs.filterdir("/GF11", namespaces=["details"]))
        self.assertTrue(rows)
        for info in rows:
            self.assertEqual(info.name, info.get("basic", "name"))
            self.assertTrue(info.get("rspace", "name"))
            if not info.is_dir:
                self.assertIsInstance(info.size, int)
                datetime.datetime.fromisoformat(info.get("rspace", "created"))

    def test_the_shim_still_uses_bare_global_id_segments(self):
        """Galaxy builds its URIs from the segment, so those must stay stable identifiers."""
        fs = self.galaxy_style_filesystem()
        self.assertTrue(all(n[:2].isalpha() and n[2:].isdigit() for n in fs.listdir("/")))

    def test_the_shim_keeps_its_released_names(self):
        """Names 2.7.x exported from the shim; the code now lives in rspace_client.fs.gallery."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            from rspace_client.eln import fs as shim
        for name in ("GalleryFilesystem", "GalleryInfo", "GallerySectionMismatch", "Placement",
                     "MISCELLANEOUS_SECTION", "ON_MISMATCH_RAISE", "ON_MISMATCH_REROUTE",
                     "classify_media_section", "is_folder"):
            self.assertTrue(hasattr(shim, name), name)
        self.assertEqual("Miscellaneous", shim.classify_media_section("data.xyz"))

    def test_the_shim_warns_on_construction(self):
        from rspace_client.eln.fs import GalleryFilesystem
        with self.assertWarns(DeprecationWarning):
            GalleryFilesystem(self.url, "k")


if __name__ == "__main__":
    unittest.main()
