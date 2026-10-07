"""Windows DPAPI credential storage and native global hotkeys."""
from __future__ import annotations

import base64
import ctypes
from ctypes import wintypes
import sys

from core import parse_hotkey


class DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]


def _dpapi(data: bytes, decrypt: bool) -> bytes:
    if sys.platform != "win32":
        raise OSError("密钥加密仅支持 Windows。")
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    blob_pointer = ctypes.POINTER(DATA_BLOB)
    crypt32.CryptProtectData.argtypes = [blob_pointer, wintypes.LPCWSTR, blob_pointer, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, blob_pointer]
    crypt32.CryptUnprotectData.argtypes = [blob_pointer, ctypes.c_void_p, blob_pointer, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, blob_pointer]
    crypt32.CryptProtectData.restype = wintypes.BOOL
    crypt32.CryptUnprotectData.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    buf = ctypes.create_string_buffer(data)
    source = DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte)))
    result = DATA_BLOB()
    func = crypt32.CryptUnprotectData if decrypt else crypt32.CryptProtectData
    description = None if decrypt else "MathSnip API credential"
    if not func(ctypes.byref(source), description, None, None, None, 1, ctypes.byref(result)):
        raise OSError("Windows 密钥加密/解密失败，请在当前账户重新填写 API Key。")
    try:
        return ctypes.string_at(result.pbData, result.cbData)
    finally:
        kernel32.LocalFree(ctypes.cast(result.pbData, ctypes.c_void_p))


def encrypt_key(value: str) -> str:
    return base64.b64encode(_dpapi(value.encode("utf-8"), False)).decode("ascii")


def decrypt_key(value: str) -> str:
    return _dpapi(base64.b64decode(value, validate=True), True).decode("utf-8")


class HotkeyRegistry:
    """Register to the Qt GUI thread; duplicate/conflicting shortcuts roll back."""
    def __init__(self):
        self.api = ctypes.WinDLL("user32", use_last_error=True)
        self.api.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
        self.api.RegisterHotKey.restype = wintypes.BOOL
        self.api.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
        self.api.UnregisterHotKey.restype = wintypes.BOOL
        self.bindings: dict[int, str] = {}
        self.values: dict[str, str] = {}

    def close(self):
        for identifier in self.bindings:
            self.api.UnregisterHotKey(None, identifier)
        self.bindings.clear()
        self.values.clear()

    def _register(self, values: dict[str, str]):
        for index, (mode, value) in enumerate(values.items(), 0x5200):
            modifier, vk = parse_hotkey(value)
            if not self.api.RegisterHotKey(None, index, modifier, vk):
                raise ValueError(f"快捷键 {value} 已被占用，请换一个。")
            self.bindings[index] = mode
        self.values = dict(values)

    def replace(self, values: dict[str, str]):
        parsed = [parse_hotkey(v) for v in values.values()]
        if len(set(parsed)) != len(parsed):
            raise ValueError("三个快捷键不能重复。")
        previous = dict(self.values)
        self.close()
        try:
            self._register(values)
        except ValueError as exc:
            self.close()
            try:
                self._register(previous)
            except ValueError:
                self.close()
                raise ValueError(f"{exc} 原快捷键恢复失败，请重新保存设置。") from None
            raise
