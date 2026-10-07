"""Native smoke tests execute only on Windows and do not call Mathpix."""
import sys
import unittest
from unittest.mock import MagicMock

from core import DEFAULT_HOTKEYS
from windows_support import HotkeyRegistry, decrypt_key, encrypt_key


class RegistryTests(unittest.TestCase):
    def registry(self):
        registry = HotkeyRegistry.__new__(HotkeyRegistry)
        registry.api = MagicMock()
        registry.api.RegisterHotKey.return_value = True
        registry.bindings = {}
        registry.values = {}
        return registry

    def test_duplicate_is_rejected_before_mutation(self):
        registry = self.registry()
        registry.replace(DEFAULT_HOTKEYS)
        count = registry.api.RegisterHotKey.call_count
        with self.assertRaises(ValueError):
            registry.replace({"latex": "Alt+Q", "word": "alt+q"})
        self.assertEqual(registry.api.RegisterHotKey.call_count, count)
        self.assertEqual(registry.values, DEFAULT_HOTKEYS)

    def test_conflict_rolls_back(self):
        registry = self.registry()
        registry.replace(DEFAULT_HOTKEYS)
        registry.api.RegisterHotKey.side_effect = [True, False, True, True, True]
        with self.assertRaises(ValueError):
            registry.replace({"latex": "Ctrl+Q", "display": "Ctrl+W", "word": "Ctrl+E"})
        self.assertEqual(registry.values, DEFAULT_HOTKEYS)
        self.assertEqual(len(registry.bindings), 3)


@unittest.skipUnless(sys.platform == "win32", "Windows DPAPI required")
class NativeWindowsTests(unittest.TestCase):
    def test_dpapi_roundtrip(self):
        encrypted = encrypt_key("example-test-key")
        self.assertNotIn("example-test-key", encrypted)
        self.assertEqual(decrypt_key(encrypted), "example-test-key")


if __name__ == "__main__":
    unittest.main()
