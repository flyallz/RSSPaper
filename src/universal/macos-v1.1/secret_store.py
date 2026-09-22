"""Keep the translation API key in the current user's macOS Keychain."""

from __future__ import annotations

from pathlib import Path

SERVICE = "com.flyall.JournalRadar.Universal"
ACCOUNT = "translation-api-key"


def _mac_keyring():
    # Select the native backend explicitly. Frozen apps cannot always discover
    # keyring's entry points, and a fallback to a plaintext backend is unsafe.
    from keyring.backends.macOS import Keyring

    return Keyring()


def save_api_key(path: Path, key: str) -> None:
    """Preserve the Windows function signature; never put the key at *path*."""
    backend = _mac_keyring()
    if key:
        backend.set_password(SERVICE, ACCOUNT, key)
    elif backend.get_password(SERVICE, ACCOUNT) is not None:
        backend.delete_password(SERVICE, ACCOUNT)


def load_api_key(path: Path) -> str:
    """Read the key from Keychain, returning an empty string when absent."""
    return _mac_keyring().get_password(SERVICE, ACCOUNT) or ""
