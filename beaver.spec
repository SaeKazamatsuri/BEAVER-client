# -*- mode: python ; coding: utf-8 -*-
a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('transcription\\vosk.exe', 'transcription'),
        ('transcription\\libvosk.dll', 'transcription'),
        ('transcription\\libgcc_s_seh-1.dll', 'transcription'),
        ('transcription\\libstdc++-6.dll', 'transcription'),
        ('transcription\\libwinpthread-1.dll', 'transcription'),
    ],
    hiddenimports=['screeninfo'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='beaver',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['favicon.ico'],
)
