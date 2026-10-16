import base64
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import app
from credentials import configure_password, load_hash, save_password, check_password_hash


class PasswordTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / '.sharedserver.json'

    def tearDown(self):
        self.temp.cleanup()

    def test_password_persists_without_plaintext(self):
        hashed = save_password('my-password', self.path)
        self.assertNotIn('my-password', self.path.read_text())
        self.assertEqual(load_hash(self.path), hashed)
        self.assertTrue(check_password_hash(hashed, 'my-password'))
        self.assertFalse(check_password_hash(hashed, 'wrong'))
        with patch('credentials.getpass.getpass', side_effect=AssertionError('must not prompt')):
            self.assertEqual(configure_password(path=self.path), hashed)

    def test_first_setup_and_reset(self):
        with patch('credentials.getpass.getpass', side_effect=['short', 'short', 'abcdef', 'different', 'original', 'original']):
            original = configure_password(path=self.path)
        with patch('credentials.getpass.getpass', side_effect=['replacement', 'replacement']):
            updated = configure_password(reset=True, path=self.path)
        self.assertNotEqual(original, updated)
        self.assertTrue(check_password_hash(load_hash(self.path), 'replacement'))

    def test_corrupt_config_can_be_reset(self):
        self.path.write_text('invalid')
        with self.assertRaises(RuntimeError):
            load_hash(self.path)
        with patch('credentials.getpass.getpass', side_effect=['new-password', 'new-password']):
            configure_password(reset=True, path=self.path)
        self.assertTrue(check_password_hash(load_hash(self.path), 'new-password'))

    def test_saved_password_authentication_and_qr(self):
        hashed = save_password('fixed-password', self.path)
        def headers(password):
            token = base64.b64encode(f'shared:{password}'.encode()).decode()
            return {'Authorization': 'Basic ' + token}
        with patch.object(app, 'ACCESS_TOKEN', None), patch.object(app, 'PASSWORD_HASH', hashed), patch.object(app, 'lan_url', return_value='http://192.168.1.20:5000'):
            client = app.app.test_client()
            self.assertEqual(client.get('/api/files', headers=headers('wrong')).status_code, 401)
            response = client.get('/access-qr.svg', headers=headers('fixed-password'))
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.mimetype, 'image/svg+xml')
            self.assertIn(b'<svg', response.data)
            self.assertNotIn(b'fixed-password', response.data)
            self.assertEqual(client.get('/access-qr.svg').status_code, 401)
