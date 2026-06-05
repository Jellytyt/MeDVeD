# -*- mode: python ; coding: utf-8 -*-
# onedir build: the app ships as a folder (MeDVeD.exe + _internal\) instead of a
# single self-extracting exe. At launch nothing is unpacked to a temp _MEI dir —
# python313.dll and sing-box.exe sit on disk next to the exe and load directly.
# That makes the "Failed to load Python DLL ... LoadLibrary" first-run race
# (onefile self-extraction fighting the antivirus scan) physically impossible.
# An Inno Setup installer (MeDVeD.iss) wraps this folder for distribution.
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

datas = []
datas += collect_data_files('customtkinter')

hiddenimports = []
hiddenimports += collect_submodules('pystray')
# PIL.ImageTk is imported lazily inside flags.py (procedural country flags) — list
# it explicitly so the frozen build can turn a flag image into a Tk PhotoImage.
hiddenimports += ['PIL.Image', 'PIL.ImageDraw', 'PIL.ImageTk', 'yaml']


datas += [
    ('assets/medved.ico', 'assets'),
    ('assets/medved_active.png', 'assets'),
    ('assets/medved_inactive.png', 'assets'),
    ('CHANGELOG.md', '.'),  # read at runtime for the "What's new" dialog
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
    [],
    exclude_binaries=True,   # onedir: deps go into _internal\, not into the exe
    name='MeDVeD',
    icon='assets/medved.ico',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,               # UPX packing also trips AV heuristics — drop it
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='MeDVeD',           # -> dist\MeDVeD\ (MeDVeD.exe + _internal\)
)
