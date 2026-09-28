# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
import PySide6

SOURCE_ROOT = Path(SPECPATH).parents[1]


a = Analysis(
    ['app.py'],
    pathex=[str(SOURCE_ROOT)],
    binaries=[],
    datas=[('assets\\icon.svg', 'assets')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["journal_radar.platform.macos_keychain"],
    noarchive=False,
    optimize=0,
)
# A Poppler installation on the build machine puts ICU 78 on PATH. Qt's
# Windows wheel uses the Windows system ICU instead; bundling Poppler's copy
# shadows it and prevents QtCore from loading on clean machines.
a.binaries = [entry for entry in a.binaries if Path(entry[0]).name.lower() not in {"icuuc.dll", "icudt78.dll"}]

# The Python installation has an older VC runtime than the PySide6 wheel.
# Keep the matching PySide6 runtime at the application root where the
# PyInstaller bootloader searches first.
qt_folder = Path(PySide6.__file__).resolve().parent
for runtime_name in ("VCRUNTIME140.dll", "VCRUNTIME140_1.dll"):
    a.binaries = [entry for entry in a.binaries if entry[0].lower() != runtime_name.lower()]
    a.binaries.append((runtime_name, str(qt_folder / runtime_name), "BINARY"))
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='JournalRadar',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['assets\\icon.ico'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='JournalRadar',
)
