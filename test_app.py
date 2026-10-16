import base64
from concurrent.futures import ThreadPoolExecutor
import io
import tempfile
import unittest
import zipfile
from pathlib import Path
import app


class FileTransferTests(unittest.TestCase):
    def setUp(self):
        self.old_token = app.ACCESS_TOKEN
        app.ACCESS_TOKEN = 'test-password'
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / 'shared'
        self.root.mkdir()
        app.app.config.update(TESTING=True, UPLOAD_FOLDER=self.root)
        self.client = app.app.test_client()
        token = base64.b64encode(f'shared:{app.ACCESS_TOKEN}'.encode()).decode()
        self.headers = {'Authorization': f'Basic {token}', 'X-SharedServer': '1'}

    def tearDown(self):
        app.ACCESS_TOKEN = self.old_token
        self.temp.cleanup()

    def upload(self, name, content=b'hello'):
        return self.client.post('/upload', data={'files': (io.BytesIO(content), name)}, headers=self.headers)

    def test_authentication_and_csrf(self):
        self.assertEqual(self.client.get('/api/files').status_code, 401)
        self.assertEqual(self.client.get('/', headers=self.headers).status_code, 200)
        self.assertEqual(self.client.post('/delete/test', headers={**self.headers, 'Origin': 'http://evil.test'}).status_code, 403)
        self.assertEqual(self.client.post('/delete/test', headers={'Authorization': self.headers['Authorization']}).status_code, 403)

    def test_upload_collision_download_delete(self):
        self.assertEqual(self.upload('中文.txt').status_code, 200)
        self.assertEqual(self.upload('中文.txt', b'new').json['files'][0]['name'], '中文 (1).txt')
        response = self.client.get('/download/中文.txt', headers=self.headers)
        self.assertEqual(response.data, b'hello')
        response.close()
        self.assertEqual(len(self.client.get('/api/files', headers=self.headers).json), 2)
        self.assertEqual(self.client.post('/delete/中文.txt', headers=self.headers).status_code, 200)
        self.assertFalse((self.root / '中文.txt').exists())

    def test_traversal_and_symlinks(self):
        outside = self.root.parent / 'shared-secret'
        outside.mkdir()
        (outside / 'secret').write_text('private')
        (self.root / 'link').symlink_to(outside, target_is_directory=True)
        for route in ['/download/../shared-secret/secret', '/download/link/secret', '/delete/../shared-secret', '/delete/link']:
            response = self.client.open(route, method='POST' if route.startswith('/delete') else 'GET', headers=self.headers)
            self.assertEqual(response.status_code, 403, route)
        self.assertEqual(self.upload('../escape').status_code, 400)
        self.assertTrue((outside / 'secret').exists())

    def test_folder_zip_excludes_symlinks_and_preserves_empty_dirs(self):
        folder = self.root / 'folder'
        folder.mkdir()
        (folder / 'empty').mkdir()
        (folder / 'ok.txt').write_text('ok')
        secret = self.root.parent / 'secret'
        secret.write_text('private')
        (folder / 'link').symlink_to(secret)
        response = self.client.get('/download/folder', headers=self.headers)
        with zipfile.ZipFile(io.BytesIO(response.data)) as archive:
            self.assertEqual(set(archive.namelist()), {'empty/', 'ok.txt'})
        response.close()
        self.assertFalse((self.root / 'folder.zip').exists())

    def test_concurrent_uploads_preserve_every_file(self):
        def upload(index):
            with app.app.test_client() as client:
                return client.post('/upload', data={'files': (io.BytesIO(str(index).encode()), 'same.txt')}, headers=self.headers).status_code
        with ThreadPoolExecutor(max_workers=4) as pool:
            self.assertEqual(list(pool.map(upload, range(8))), [200] * 8)
        self.assertEqual({item.read_bytes() for item in self.root.iterdir()}, {str(i).encode() for i in range(8)})
        self.assertEqual(len(list(self.root.iterdir())), 8)

    def test_range_download(self):
        self.upload('range.txt', b'0123456789')
        response = self.client.get('/download/range.txt', headers={**self.headers, 'Range': 'bytes=2-5'})
        self.assertEqual(response.status_code, 206)
        self.assertEqual(response.data, b'2345')
        response.close()

    def test_request_size_limit(self):
        previous = app.app.config['MAX_CONTENT_LENGTH']
        try:
            app.app.config['MAX_CONTENT_LENGTH'] = 100
            response = self.upload('large', b'x' * 200)
            self.assertEqual(response.status_code, 413)
            self.assertFalse(list(self.root.iterdir()))
        finally:
            app.app.config['MAX_CONTENT_LENGTH'] = previous


if __name__ == '__main__':
    unittest.main()
