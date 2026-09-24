"""Keep the translation API key in the current user's macOS Keychain."""

from __future__ import annotations

from pathlib import Path
import subprocess

SERVICE = "com.flyall.JournalRadar.Universal"
ACCOUNT = "translation-api-key"


def _run_security(*args: str) -> subprocess.CompletedProcess[str]:
    """Call macOS' built-in Keychain client without a Python runtime plugin."""
    return subprocess.run(
        ["/usr/bin/security", *args],
        check=False,
        capture_output=True,
        text=True,
    )


def save_api_key(path: Path, key: str) -> None:
    """Preserve the Windows function signature; never put the key at *path*."""
    if key:
        result = _run_security(
            "add-generic-password", "-U", "-s", SERVICE, "-a", ACCOUNT, "-w", key
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "无法写入 macOS 钥匙串")
    else:
        _run_security("delete-generic-password", "-s", SERVICE, "-a", ACCOUNT)


def load_api_key(path: Path) -> str:
    """Read the key from Keychain, returning an empty string when absent."""
    result = _run_security(
        "find-generic-password", "-s", SERVICE, "-a", ACCOUNT, "-w"
    )
    if result.returncode != 0:
        return ""
    return result.stdout.rstrip("\r\n")
