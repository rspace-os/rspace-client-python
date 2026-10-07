"""
Regression tests from the 2026-10-07 review pass over rspace_client.fs: each test pins a
behaviour that the review found wrong against the mock RSpace server.
"""
from rspace_client.fs import GalleryFilesystem, RSpaceFilesystem
from rspace_client.fs.paths import last_segment
from rspace_client.tests.mock_server_case import MockServerTestCase


def names(fs, path):
    return [last_segment(n) for n in fs.ls(path, detail=False)]


class ReviewRegressionTest(MockServerTestCase):

    def test_resolving_a_name_does_not_fetch_sizes(self):
        """A lookup lists the parent to find a name; the per-file size fetch that a listing
        pays for is wasted there. Before: 6 calls for info() of a file by name."""
        fs = GalleryFilesystem(self.url, "k")  # fetch_sizes=True by default
        before = self.calls()
        entry = fs.info("Images/gel.jpg")
        # gallery root id, root listing (to find Images), Images listing, the file's record
        self.assertEqual(4, self.calls() - before)
        self.assertEqual(868, entry["size"])
        before = self.calls()
        sizes = [e["size"] for e in fs.ls("Images") if e["type"] == "file"]
        self.assertEqual([1096, 868], sizes)  # a real listing still tops the sizes up
        self.assertEqual(1 + 2, self.calls() - before)

    def test_double_star_glob_is_recursive_not_a_search(self):
        fs = GalleryFilesystem(self.url, "k")
        everything = fs.glob("**")
        self.assertIn("Images/gel.jpg", everything)
        self.assertIn("Documents/data.csv", everything)
        self.assertEqual(["Documents/data.csv", "Documents/data [GL112].csv"], fs.glob("Documents/*data*"))

    def test_a_write_drops_the_listings_cache(self):
        fs = GalleryFilesystem(self.url, "k", writable=True, use_listings_cache=True)
        self.assertNotIn("new.txt", names(fs, "Documents"))
        with fs.open("Documents/new.txt", "wb") as handle:
            handle.write(b"x")
        self.assertIn("new.txt", names(fs, "Documents"))

    def test_a_move_out_of_the_gallery_is_refused_before_anything_is_copied(self):
        fs = GalleryFilesystem(self.url, "k", writable=True, allow_delete=True)
        with self.assertRaises(NotImplementedError):
            fs.mv("Documents/data.csv", "Documents/moved.csv")
        self.assertNotIn("moved.csv", names(fs, "Documents"))
        mount = RSpaceFilesystem(self.url, "k", writable=True, allow_delete=True)
        with self.assertRaises(NotImplementedError):
            mount.mv("gallery/Documents/data.csv", "gallery/Documents/moved.csv")
        self.assertNotIn("moved.csv", names(mount, "gallery/Documents"))
        # where the source can be removed a move is an unlink plus a link
        mount.mv("workspace/Project Alpha/Alpha protocol/Results/data.csv", "inventory/Containers/Freezer -80/data.csv")
        self.assertIn("data.csv", names(mount, "inventory/Containers/Freezer -80"))
        self.assertNotIn("data.csv", names(mount, "workspace/Project Alpha/Alpha protocol/Results"))

    def test_list_paths_are_accepted_where_fsspec_passes_them(self):
        fs = GalleryFilesystem(self.url, "k")
        self.assertEqual(["Images", "Documents/data.csv"],
                         fs._strip_protocol(["rspace-gallery://Images/", "Documents/data.csv"]))
        self.assertEqual(2, len(fs.cat(["Documents/data.csv", "Images/gel.jpg"])))
        mount = RSpaceFilesystem(self.url, "k")
        self.assertEqual(["gallery/Images"], mount._strip_protocol(["gallery/Images/"]))

    def test_recursive_put_creates_the_folders_it_copies(self):
        """fsspec's put() hands directories to put_file and expects the backend to make them."""
        import os
        import tempfile
        fs = RSpaceFilesystem(self.url, "k", writable=True)
        tmp = tempfile.mkdtemp()
        os.makedirs(os.path.join(tmp, "img", "sub"))
        with open(os.path.join(tmp, "img", "a.txt"), "wb") as handle:
            handle.write(b"a")
        with open(os.path.join(tmp, "img", "sub", "b.txt"), "wb") as handle:
            handle.write(b"b")
        fs.put(os.path.join(tmp, "img") + "/", "gallery/Documents/", recursive=True)
        self.assertIn("gallery/Documents/sub/b.txt", fs.find("gallery/Documents"))
        self.assertEqual(b"a", fs.cat_file("gallery/Documents/a.txt"))
