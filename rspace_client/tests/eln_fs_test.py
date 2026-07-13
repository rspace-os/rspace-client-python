from unittest.mock import patch, MagicMock, ANY
import unittest
from rspace_client.eln.fs import (
    path_to_id,
    GalleryFilesystem,
    GallerySectionMismatch,
    classify_media_section,
)
from rspace_client.client_base import ClientBase
from io import BytesIO


def mock_failed_upload_post(url, *args, **kwargs):
    """A /files upload that the server rejects (e.g. wrong Gallery section)."""
    mock_response = MagicMock()
    mock_response.status_code = 400
    mock_response.headers = {'Content-Type': 'application/json'}
    mock_response.json.return_value = {
        'message': 'File type not allowed in this folder', 'errors': []
    }
    mock_response.raise_for_status.side_effect = Exception('400 Bad Request')
    return mock_response

def mock_requests_get(url, *args, **kwargs):
    mock_response = MagicMock()
    if url.endswith('/folders/tree'):
        mock_response.json.return_value = {
            'records': [
                {'id': '123', 'name': 'Gallery'}
            ]
        }
    elif url.endswith('/folders/tree/123'):
        mock_response.json.return_value = {
            'records': [
                {'globalId': 'GF123', 'name': 'Folder1'},
                {'globalId': 'GL456', 'name': 'File1'},
                {'globalId': 'GF789', 'name': 'Folder2'},
                {'globalId': 'GL012', 'name': 'File2'}
            ]
        }
    elif url.endswith('/folders/tree/456'):
            mock_response.json.return_value = {
                'records': [
                ]
            }
    elif url.endswith('/folders/123'):
        mock_response.json.return_value = {
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
    elif url.endswith('/folders/456'):
        mock_response.json.return_value = {
            'id': '456',
            'globalId': 'GF456',
            'name': 'newFolder',
            'size': 0,
            'created': '2025-02-11T16:00:16.392Z',
            'lastModified': '2025-02-11T16:00:16.392Z',
            'parentFolderId': 131,
            'notebook': False,
            'mediaType': 'Images',
            'pathToRootFolder': None,
            '_links': [{'link': 'http://localhost:8080/api/v1/folders/306', 'rel': 'self'}]
        }
    elif url.endswith('/files/123'):
        mock_response.json.return_value = {
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
    else:
        mock_response.json.return_value = {}
    mock_response.headers = {'Content-Type': 'application/json'}
    return mock_response

def mock_requests_post(url, *args, **kwargs):
    mock_response = MagicMock()
    mock_response.json.return_value = {
        'id': '456',
        'globalId': 'GF456',
        'name': 'newFolder',
        'size': 0,
        'created': '2025-02-11T16:00:16.392Z',
        'lastModified': '2025-02-11T16:00:16.392Z',
        'parentFolderId': 131,
        'notebook': False,
        'mediaType': 'Images',
        'pathToRootFolder': None,
        '_links': [{'link': 'http://localhost:8080/api/v1/folders/306', 'rel': 'self'}]
        }
    mock_response.headers = {'Content-Type': 'application/json'}
    return mock_response


class ElnFilesystemTest(unittest.TestCase):

    @patch('requests.get', side_effect=mock_requests_get)
    def setUp(self, mock_get) -> None:
        super().setUp()
        self.fs = GalleryFilesystem("https://example.com", "api_key")

    def test_path_to_id(self):
        self.assertEqual("123", path_to_id("GF123"))
        self.assertEqual("123", path_to_id("/GF123"))
        self.assertEqual("456", path_to_id("GF123/GF456"))
        self.assertEqual("456", path_to_id("/GF123/GF456"))

    @patch('requests.get', side_effect=mock_requests_get)
    def test_get_info_folder(self, mock_get):
        folder_info = self.fs.getinfo("GF123")
        self.assertEqual("GF123", folder_info.raw["basic"]["name"])
        self.assertTrue(folder_info.raw["basic"]["is_dir"])
        self.assertEqual(0, folder_info.raw["details"]["size"])

    @patch('requests.get', side_effect=mock_requests_get)
    def test_get_info_file(self, mock_get):
        file_info = self.fs.getinfo("GL123")
        self.assertEqual("GL123", file_info.raw["basic"]["name"])
        self.assertFalse(file_info.raw["basic"]["is_dir"])
        self.assertEqual(1024, file_info.raw["details"]["size"])

    @patch('requests.get', side_effect=mock_requests_get)
    def test_listdir_root(self, mock_list_folder_tree):
        result = self.fs.listdir('/')
        expected = ['GF123', 'GL456', 'GF789', 'GL012']
        self.assertEqual(result, expected)

    @patch('requests.get', side_effect=mock_requests_get)
    def test_listdir_root_specific_folder(self, mock_list_folder_tree):
        expected = ['GF123', 'GL456', 'GF789', 'GL012']
        result = self.fs.listdir('GF123')
        self.assertEqual(result, expected)

    @patch('requests.request', side_effect=mock_requests_post)
    @patch('requests.get', side_effect=mock_requests_get)
    def test_makedir(self, mock_get, mock_post):
        self.fs.makedir('GF123/newFolder')
        mock_post.assert_called_once_with(
            'POST',
            'https://example.com/api/v1/folders',
            json={'name': 'newFolder', 'parentFolderId': 123, 'notebook': False},
            headers=ANY
        )

    @patch('requests.request', side_effect=mock_requests_post)
    @patch('requests.get', side_effect=mock_requests_get)
    def test_removedir(self, mock_get, mock_post):
        self.fs.removedir('GF456')
        mock_post.assert_called_once_with(
            'DELETE',
            'https://example.com/api/v1/folders/456',
            json=ANY,
            headers=ANY
        )

    @patch('requests.get')
    def test_download(self, mock_get):
        mock_response = MagicMock()
        mock_response.iter_content = MagicMock(return_value=[b'chunk1', b'chunk2', b'chunk3'])
        mock_get.return_value = mock_response
        file_obj = BytesIO()
        self.fs.download('/GL123', file_obj)
        file_obj.seek(0)
        self.assertEqual(file_obj.read(), b'chunk1chunk2chunk3')
        mock_get.assert_called_once_with(
            'https://example.com/api/v1/files/123/file',
            headers=ANY
        )

    @patch('requests.post')
    def test_upload(self, mock_post):
        mock_response = MagicMock()
        mock_response.json.return_value = {'id': '456'}
        mock_post.return_value = mock_response
        file_obj = BytesIO(b'test file content')
        self.fs.upload('/GF123', file_obj)
        mock_post.assert_called_once_with(
            'https://example.com/api/v1/files',
            files={'file': file_obj},
            data={'folderId': 123},
            headers=ANY
        )

    def test_classify_media_section(self):
        self.assertEqual('Images', classify_media_section('photo.png'))
        self.assertEqual('Images', classify_media_section('photo.JPG'))
        self.assertEqual('Videos', classify_media_section('clip.mp4'))
        self.assertEqual('Chemistry', classify_media_section('reaction.mol'))
        # unrecognised extensions fall through to the Documents catch-all
        self.assertEqual('Documents', classify_media_section('report.pdf'))
        self.assertEqual('Documents', classify_media_section('data.xyz'))
        # no filename / no extension -> cannot guess
        self.assertIsNone(classify_media_section('noextension'))
        self.assertIsNone(classify_media_section(None))

    @patch('requests.get', side_effect=mock_requests_get)
    @patch('requests.post', side_effect=mock_failed_upload_post)
    def test_upload_wrong_section_raises_mismatch(self, mock_post, mock_get):
        # Folder GF123 is in the 'Images' section (see mock_requests_get);
        # uploading a PDF there is rejected by the server.
        file_obj = BytesIO(b'%PDF-1.4 fake')
        file_obj.name = 'data.pdf'
        with self.assertRaises(GallerySectionMismatch) as ctx:
            self.fs.upload('/GF123', file_obj)
        err = ctx.exception
        self.assertEqual('Images', err.folder_section)
        self.assertEqual('GF123', err.folder_global_id)
        self.assertEqual('Documents', err.file_media_type)
        self.assertIn('Images', str(err))
        self.assertIn('data.pdf', str(err))
        # the original server message is preserved
        self.assertIn('File type not allowed', str(err))

    @patch('requests.post', side_effect=mock_failed_upload_post)
    def test_upload_no_folder_reraises_original(self, mock_post):
        # With no target folder the server auto-routes; a failure here is not a
        # section mismatch and must surface unchanged.
        file_obj = BytesIO(b'x')
        with self.assertRaises(ClientBase.ApiError) as ctx:
            self.fs.upload('', file_obj)
        self.assertNotIsInstance(ctx.exception, GallerySectionMismatch)


if __name__ == '__main__':
    unittest.main()
