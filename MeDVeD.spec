# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

datas = []
datas += collect_data_files('customtkinter')

hiddenimports = []
hiddenimports += collect_submodules('pystray')
hiddenimports += ['PIL.Image', 'PIL.ImageDraw', 'yaml']


datas += [
    ('assets/medved.ico', 'assets'),
    ('assets/medved_active.png', 'assets'),
    ('assets/medved_inactive.png', 'assets'),
]

a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=[('sing-box.exe', '.')],
    datas=datas,
    hiddenimports=hiddenimports,
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
    name='MeDVeD',
    icon='assets/medved.ico',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=['sing-box.exe'],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
