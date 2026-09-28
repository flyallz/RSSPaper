"""Build and smoke-test the shared application on the current platform.

Run from the repository root with python scripts/build-universal.py.
Requires requirements-build.txt. Output stays in dist/, outside source control.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from journal_radar.config import VERSION  # noqa: E402 - source checkout bootstrap


def run(arguments: list[str], cwd: Path = ROOT, env: dict[str, str] | None = None) -> None:
    subprocess.run(arguments, cwd=cwd, env=env, check=True)


def build(skip_tests: bool = False) -> Path:
    if sys.platform not in ("darwin", "win32"):
        raise SystemExit("Build on macOS or Windows.")
    platform = "Mac-arm64" if sys.platform == "darwin" else "Windows-Portable"
    folder = ROOT / "src/universal" / ("macos-v1.1" if sys.platform == "darwin" else "v1.1")
    spec = "JournalRadar-mac.spec" if sys.platform == "darwin" else "JournalRadar.spec"
    dist = ROOT / "dist" / platform
    env = {
        **os.environ,
        "PYTHONPATH": str(ROOT / "src"),
        "QT_QPA_PLATFORM": "offscreen",
        "PYINSTALLER_CONFIG_DIR": str(ROOT / "dist/pyinstaller-config"),
    }
    if not skip_tests:
        run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"], env=env)
    run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--distpath",
            str(dist),
            "--workpath",
            str(ROOT / "dist" / (platform + "-build")),
            spec,
        ],
        cwd=folder,
        env=env,
    )
    if sys.platform == "darwin":
        application = dist / "JournalRadar.app"
        executable = application / "Contents/MacOS/JournalRadar"
        run(["codesign", "--verify", "--deep", "--strict", str(application)])
    else:
        application = dist / "JournalRadar"
        executable = application / "JournalRadar.exe"
        shutil.copy2(folder / "README.txt", application / "README.txt")
    # A fresh test directory prevents packaged smoke tests from touching real data.
    with tempfile.TemporaryDirectory(prefix="journalradar-build-") as temporary:
        smoke_env = {**env, "JOURNAL_RADAR_HOME": temporary}
        run([str(executable), "--self-test"], env=smoke_env)
        run([str(executable), "--gui-smoke"], env=smoke_env)
    artifacts = ROOT / "dist/artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    archive = artifacts / f"JournalRadar-Universal-v{VERSION}-{platform}.zip"
    if sys.platform == "darwin":
        run(
            ["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", str(application), str(archive)]
        )
    else:
        shutil.make_archive(str(archive.with_suffix("")), "zip", dist, "JournalRadar")
    with archive.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    (artifacts / f"SHA256SUMS-{platform}.txt").write_text(
        f"{digest}  {archive.name}\n", encoding="utf-8"
    )
    return archive


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--skip-tests", action="store_true", help="For CI after its test job has passed."
    )
    args = parser.parse_args()
    print(build(args.skip_tests))
