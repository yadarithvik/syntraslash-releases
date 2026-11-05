import hashlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from model_install import ModelInstaller, InstallPaused

DATA = b'GGUF' + bytes(range(256)) * 8192
DIGEST = hashlib.sha256(DATA).hexdigest()


class Response(io.BytesIO):
    def __init__(self, data, status=200, headers=None):
        super().__init__(data)
        self.status = status
        self.headers = headers or {'Content-Length': str(len(data))}


class ModelInstallTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.opener = Mock(return_value=Response(DATA))
        self.installer = ModelInstaller(self.tmp.name, size=len(DATA), digest=DIGEST,
                                        opener=self.opener)

    def test_download_verifies_and_marks_install(self):
        path = self.installer.download()
        self.assertEqual(path.read_bytes(), DATA)
        self.assertEqual(self.installer.installed(), path)
        self.assertFalse(self.installer.partial.exists())

    def test_resume_requests_exact_offset(self):
        offset = 10000
        self.installer.partial.write_bytes(DATA[:offset])
        self.opener.return_value = Response(DATA[offset:], 206,
            {'Content-Length': str(len(DATA)-offset),
             'Content-Range': f'bytes {offset}-{len(DATA)-1}/{len(DATA)}'})
        self.assertEqual(self.installer.download().read_bytes(), DATA)
        self.assertEqual(self.opener.call_args.args[0].get_header('Range'), f'bytes={offset}-')

    def test_ignored_range_restarts_without_duplicate_bytes(self):
        self.installer.partial.write_bytes(DATA[:1000])
        self.assertEqual(self.installer.download().read_bytes(), DATA)

    def test_invalid_range_never_touches_saved_prefix(self):
        self.installer.partial.write_bytes(DATA[:1000])
        self.opener.return_value = Response(DATA[1000:], 206,
            {'Content-Range': f'bytes 0-{len(DATA)-1}/{len(DATA)}'})
        with self.assertRaisesRegex(ValueError, 'range'):
            self.installer.download()
        self.assertEqual(self.installer.partial.read_bytes(), DATA[:1000])

    def test_truncated_transfer_preserves_progress(self):
        self.opener.return_value = Response(DATA[:1000], headers={'Content-Length':str(len(DATA))})
        with self.assertRaisesRegex(OSError, 'interrupted'):
            self.installer.download()
        self.assertEqual(self.installer.partial.read_bytes(), DATA[:1000])
        self.assertFalse(self.installer.path.exists())

    def test_corrupt_download_is_not_installed(self):
        self.opener.return_value = Response(DATA[:-1] + b'x')
        with self.assertRaisesRegex(ValueError, 'checksum'):
            self.installer.download()
        self.assertFalse(self.installer.path.exists())
        self.assertFalse(self.installer.partial.exists())

    def test_pause_preserves_download_and_can_resume(self):
        def pause(phase, done, total):
            if phase == 'downloading' and done:
                self.installer.cancel.set()
        with self.assertRaises(InstallPaused):
            self.installer.download(pause)
        offset = self.installer.partial.stat().st_size
        self.assertGreater(offset, 0)
        self.assertFalse(self.installer.path.exists())
        self.installer.cancel.clear()
        self.opener.return_value = Response(DATA[offset:], 206,
            {'Content-Length':str(len(DATA)-offset),
             'Content-Range':f'bytes {offset}-{len(DATA)-1}/{len(DATA)}'})
        self.assertEqual(self.installer.download().read_bytes(), DATA)

    def test_disk_full_does_not_start_network(self):
        with patch('model_install.shutil.disk_usage', return_value=Mock(free=1)):
            with self.assertRaisesRegex(OSError, 'space'):
                self.installer.download()
        self.opener.assert_not_called()

    def test_modified_installed_file_invalidates_marker(self):
        self.installer.download()
        self.installer.path.write_bytes(DATA[:-1] + b'x')
        self.assertIsNone(self.installer.installed())

    def test_import_verifies_before_replacing_model(self):
        source = Path(self.tmp.name) / 'existing.gguf'
        source.write_bytes(DATA)
        self.assertEqual(self.installer.import_model(source).read_bytes(), DATA)
        source.write_bytes(DATA[:-1] + b'x')
        with self.assertRaises(ValueError):
            self.installer.import_model(source)
        self.assertEqual(self.installer.path.read_bytes(), DATA)

    def test_completed_partial_is_verified_without_network(self):
        self.installer.partial.write_bytes(DATA)
        self.installer.download()
        self.opener.assert_not_called()

    def test_wrong_magic_is_rejected(self):
        self.opener.return_value = Response(b'HTML' + DATA[4:])
        with self.assertRaisesRegex(ValueError, 'GGUF'):
            self.installer.download()

    def test_second_window_cannot_write_same_model(self):
        other = ModelInstaller(self.tmp.name, size=len(DATA), digest=DIGEST, opener=self.opener)
        with self.installer._install_lock():
            with self.assertRaisesRegex(RuntimeError, 'Another Syntra window'):
                other.download()
        self.opener.assert_not_called()


if __name__ == '__main__':
    unittest.main()
