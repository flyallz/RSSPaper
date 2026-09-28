# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

SOURCE_ROOT = Path(SPECPATH).parents[1]
import sys
sys.path.insert(0, str(SOURCE_ROOT))
from journal_radar.config import VERSION

a = Analysis(
    ['app.py'],
    pathex=[str(SOURCE_ROOT)],
    binaries=[],
    datas=[('assets/icon.svg', 'assets')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["journal_radar.platform.windows_dpapi"],
    noarchive=False,
)
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
    upx=False,
    console=False,
    target_arch='arm64',
    codesign_identity=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name='JournalRadar',
)
app = BUNDLE(
    coll,
    name='JournalRadar.app',
    icon='assets/icon.icns',
    bundle_identifier='com.flyall.JournalRadar.Universal',
    info_plist={
        'CFBundleName': '期刊雷达',
        'CFBundleDisplayName': '期刊雷达 · 通用版',
        'CFBundleShortVersionString': VERSION,
        'CFBundleVersion': VERSION,
        'LSMinimumSystemVersion': '13.0',
        'NSHighResolutionCapable': True,
    },
)
