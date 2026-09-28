"""Select native credential storage lazily, so imports work on either OS."""

import sys
from pathlib import Path


def _backend():
    if sys.platform == "darwin":
        from . import macos_keychain

        return macos_keychain
    if sys.platform == "win32":
        from . import windows_dpapi

        return windows_dpapi
    raise RuntimeError("密钥保存仅支持 macOS 和 Windows")


def save_api_key(path: Path, key: str) -> None:
    _backend().save_api_key(path, key)


def load_api_key(path: Path) -> str:
    return _backend().load_api_key(path)


def check_backend() -> None:
    """Check native bindings without reading or changing a user's credentials."""
    backend = _backend()
    if sys.platform == "darwin":
        backend.Keychain()
    else:
        probe = b"JournalRadar build check"
        encrypted = backend._windows_dpapi(probe, encrypt=True)
        if backend._windows_dpapi(encrypted, encrypt=False) != probe:
            raise RuntimeError("Windows 密钥保护自检失败")
