from unittest.mock import patch, MagicMock, ANY
import unittest
from io import BytesIO
from rspace_client.inv.attachment_fs import InventoryAttachmentFilesystem

def mock_requests_get(url, *args, **kwargs):
    mock_response = MagicMock()
    if url.endswith('/files/123'):
        mock_response.json.return_value = {
            'id': 32768,
            'globalId': 'IF32768',
            'name': 'file.png',
            'parentGlobalId': 'SS4',
            'mediaFileGlobalId': None,
            'type': 'GENERAL',
            'contentMimeType': 'image/png',
            'extension': 'png',
            'size': 40721,
            'created': '2025-02-17T11:25:03.000Z',
            'createdBy': 'user1a',
            'deleted': False,
            '_links': [
            {
                'link': 'http://localhost:8080/api/inventory/v1/files/32768',
                'rel': 'self'
            },
            {
                'link': 'http://localhost:8080/api/inventory/v1/files/32768/file',
                'rel': 'enclosure'
            }
            ]
        }
    else:
        mock_response.json.return_value = {}
    mock_response.headers = {'Content-Type': 'application/json'}
    return mock_response

def mock_requests(url, *args, **kwargs):
    mock_response = MagicMock()
    mock_response.json.return_value = {}
    mock_response.headers = {'Content-Type': 'application/json'}
    return mock_response

class InvAttachmentFilesystemTest(unittest.TestCase):

    @patch('requests.get', side_effect=mock_requests_get)
    def setUp(self, mock_get) -> None:
        super().setUp()
        self.fs = InventoryAttachmentFilesystem("https://example.com", "api_key")

    @patch('requests.get', side_effect=mock_requests_get)
    def test_get_info_folder(self, mock_get):
        folder_info = self.fs.getinfo("IF123")
        self.assertEqual("IF123", folder_info.raw["basic"]["name"])
        self.assertFalse(folder_info.raw["basic"]["is_dir"])
        self.assertEqual(40721, folder_info.raw["details"]["size"])

    @patch('requests.request', side_effect=mock_requests)
    def test_remove(self, mock_request):
        self.fs.remove("IF123")
        mock_request.assert_called_with('DELETE', 'https://example.com/api/inventory/v1/files/123', json=None, headers=ANY)

    @patch('requests.get')
    def test_download(self, mock_get):
        mock_response = MagicMock()
        mock_response.iter_content = MagicMock(return_value=[b'chunk1', b'chunk2', b'chunk3'])
        mock_get.return_value = mock_response
        file_obj = BytesIO()
        self.fs.download('/IF123', file_obj)
        file_obj.seek(0)
        self.assertEqual(file_obj.read(), b'chunk1chunk2chunk3')
        mock_get.assert_called_once_with(
            'https://example.com/api/inventory/v1/files/123/file',
            headers=ANY
        )

    @patch('requests.post')
    def test_upload(self, mock_post):
        mock_response = MagicMock()
        mock_response.json.return_value = {'id': '456'}
        mock_post.return_value = mock_response
        file_obj = BytesIO(b'test file content')
        self.fs.upload('/SS123', file_obj)
        mock_post.assert_called_once_with(
            'https://example.com/api/inventory/v1/files',
            data={'fileSettings': '{"parentGlobalId": "SS123"}'},
            files={'file': file_obj},
            headers=ANY
        )
