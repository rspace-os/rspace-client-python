from rspace_client.tests.base_test import BaseApiTest
from rspace_client.eln.fs import path_to_id

class ElnFilesystemTest(BaseApiTest):
    def test_path_to_id(self):
        self.assertEqual("123", path_to_id("GF123"))
        self.assertEqual("123", path_to_id("/GF123"))
        self.assertEqual("456", path_to_id("GF123/GF456"))
        self.assertEqual("456", path_to_id("/GF123/GF456"))
