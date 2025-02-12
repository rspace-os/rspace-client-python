from unittest.mock import patch
from rspace_client.tests.base_test import BaseApiTest
from rspace_client.eln.fs import path_to_id, GalleryFilesystem

class ElnFilesystemTest(BaseApiTest):

    @patch('rspace_client.eln.eln.ELNClient.list_folder_tree')
    def setUp(self, mock_list_folder_tree) -> None:
        super().setUp()
        mock_list_folder_tree.return_value = {
            'records': [
                {'id': '123', 'name': 'Gallery'}
            ]
        }
        self.fs = GalleryFilesystem("https://example.com", "api_key")

    def test_path_to_id(self):
        self.assertEqual("123", path_to_id("GF123"))
        self.assertEqual("123", path_to_id("/GF123"))
        self.assertEqual("456", path_to_id("GF123/GF456"))
        self.assertEqual("456", path_to_id("/GF123/GF456"))

    @patch('rspace_client.eln.eln.ELNClient.get_folder')
    @patch('rspace_client.eln.eln.ELNClient.get_file_info')
    def test_get_info(self, mock_get_file_info, mock_get_folder):
        mock_get_folder.return_value = {
            'id': '123',
            'globalId': 'GF123',
            'name': 'Test Folder',
            'size': 0,
            'created': '2025-02-11T16:00:16.392Z',
            'lastModified': '2025-02-11T16:00:16.392Z',
            'parentFolderId': 131,
            'notebook': False,
            'mediaType': 'Images',
            'pathToRootFolder': None,
            '_links': [{'link': 'http://localhost:8080/api/v1/folders/306', 'rel': 'self'}]
        }
        mock_get_file_info.return_value = {
            'id': '123',
            'globalId': 'GF123',
            'name': 'Test File',
            'size': 1024,
            'created': '2025-02-11T16:00:16.392Z',
            'lastModified': '2025-02-11T16:00:16.392Z',
            'parentFolderId': 131,
            'notebook': False,
            'mediaType': 'Images',
            'pathToRootFolder': None,
            '_links': [{'link': 'http://localhost:8080/api/v1/folders/306', 'rel': 'self'}]
        }

        folder_info = self.fs.getinfo("GF123")
        self.assertEqual("GF123", folder_info.raw["basic"]["name"])
        self.assertTrue(folder_info.raw["basic"]["is_dir"])
        self.assertEqual(0, folder_info.raw["details"]["size"])

        file_info = self.fs.getinfo("GL123")
        self.assertEqual("GL123", file_info.raw["basic"]["name"])
        self.assertFalse(file_info.raw["basic"]["is_dir"])
        self.assertEqual(1024, file_info.raw["details"]["size"])
