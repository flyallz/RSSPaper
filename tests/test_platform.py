"""Credential boundary tests never access the user's stored API key."""

import ctypes
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import Mock, patch

from journal_radar.platform import macos_keychain, secrets, windows_dpapi


class KeychainTests(unittest.TestCase):
    def fake_keychain(self):
        keychain = macos_keychain.Keychain.__new__(macos_keychain.Keychain)
        keychain.security = Mock()
        keychain.cf = Mock()
        keychain._constant = lambda name: name

        @contextmanager
        def dictionary(attributes):
            yield dict(attributes)

        keychain._dictionary = dictionary
        return keychain

    def test_missing_key_is_empty_but_denied_access_is_an_error(self):
        keychain = self.fake_keychain()
        keychain.security.SecItemCopyMatching.return_value = macos_keychain.NOT_FOUND
        self.assertEqual(keychain.load(), "")
        keychain.security.SecItemCopyMatching.return_value = -25293
        with self.assertRaisesRegex(RuntimeError, "-25293"):
            keychain.load()

    def test_save_updates_existing_key_and_adds_missing_key(self):
        keychain = self.fake_keychain()
        keychain.security.SecItemUpdate.return_value = 0
        keychain.save("fake-key")
        keychain.security.SecItemAdd.assert_not_called()
        changes = keychain.security.SecItemUpdate.call_args.args[1]
        self.assertEqual(changes["kSecValueData"], b"fake-key")
        identity = keychain.security.SecItemUpdate.call_args.args[0]
        self.assertEqual(identity["kSecAttrService"], macos_keychain.SERVICE)
        keychain.security.SecItemUpdate.return_value = macos_keychain.NOT_FOUND
        keychain.security.SecItemAdd.return_value = 0
        keychain.save("another-key")
        keychain.security.SecItemAdd.assert_called_once()

    def test_delete_missing_is_safe_but_failure_is_reported(self):
        keychain = self.fake_keychain()
        keychain.security.SecItemDelete.return_value = macos_keychain.NOT_FOUND
        keychain.save("")
        keychain.security.SecItemDelete.return_value = -25293
        with self.assertRaises(RuntimeError):
            keychain.save("")

    def test_load_decodes_utf8_and_releases_native_result(self):
        keychain = self.fake_keychain()
        payload = "测试-key".encode()
        buffer = ctypes.create_string_buffer(payload)

        def copy_matching(query, output):
            ctypes.cast(output, ctypes.POINTER(ctypes.c_void_p))[0] = 123
            return 0

        keychain.security.SecItemCopyMatching.side_effect = copy_matching
        keychain.cf.CFDataGetLength.return_value = len(payload)
        keychain.cf.CFDataGetBytePtr.return_value = ctypes.addressof(buffer)
        self.assertEqual(keychain.load(), "测试-key")
        keychain.cf.CFRelease.assert_called_once()

    @unittest.skipUnless(sys.platform == "darwin", "macOS frameworks required")
    def test_real_framework_bindings_and_query_memory_without_keychain_access(self):
        keychain = macos_keychain.Keychain()
        with keychain._dictionary({**keychain._identity(), "kSecValueData": b"test-only"}) as query:
            self.assertTrue(query)

    def test_platform_dispatch_does_not_write_a_mac_secret_to_disk(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "api-key.bin"
            backend = Mock()
            backend.load_api_key.return_value = "test-only"
            with patch.object(secrets, "_backend", return_value=backend):
                secrets.save_api_key(path, "test-only")
                self.assertEqual(secrets.load_api_key(path), "test-only")
            self.assertFalse(path.exists())

    @unittest.skipUnless(sys.platform == "win32", "Windows DPAPI required")
    def test_real_windows_dpapi_roundtrip(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "api-key.bin"
            windows_dpapi.save_api_key(path, "test-only-key")
            self.assertNotIn(b"test-only-key", path.read_bytes())
            self.assertEqual(windows_dpapi.load_api_key(path), "test-only-key")
            windows_dpapi.save_api_key(path, "")
            self.assertFalse(path.exists())
