"""Windows-user-bound API key storage using DPAPI."""

from __future__ import annotations

import ctypes
import os
from ctypes import wintypes
from pathlib import Path


class DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


def _windows_dpapi(data: bytes, encrypt: bool) -> bytes:
    if os.name != "nt":
        raise RuntimeError("API 密钥加密仅支持 Windows")
    raw_buffer = ctypes.create_string_buffer(data)
    input_blob = DATA_BLOB(len(data), ctypes.cast(raw_buffer, ctypes.POINTER(ctypes.c_byte)))
    output_blob = DATA_BLOB()
    crypt32 = ctypes.windll.crypt32
    function = crypt32.CryptProtectData if encrypt else crypt32.CryptUnprotectData
    function.argtypes = [ctypes.POINTER(DATA_BLOB), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(DATA_BLOB)]
    function.restype = wintypes.BOOL
    if not function(ctypes.byref(input_blob), None, None, None, None, 0, ctypes.byref(output_blob)):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(output_blob.pbData, output_blob.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(ctypes.cast(output_blob.pbData, ctypes.c_void_p))


def save_api_key(path: Path, key: str) -> None:
    if not key:
        if path.exists():
            path.unlink()
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_windows_dpapi(key.encode("utf-8"), encrypt=True))


def load_api_key(path: Path) -> str:
    if not path.exists():
        return ""
    return _windows_dpapi(path.read_bytes(), encrypt=False).decode("utf-8")
