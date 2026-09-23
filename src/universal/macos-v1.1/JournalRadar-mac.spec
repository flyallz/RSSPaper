# -*- mode: python ; coding: utf-8 -*-

a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=[],
    datas=[('assets/icon.svg', 'assets')],
    hiddenimports=['keyring.backends.macOS'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
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
        'CFBundleShortVersionString': '1.2.2',
        'CFBundleVersion': '1.2.2',
        'LSMinimumSystemVersion': '13.0',
        'NSHighResolutionCapable': True,
    },
)
