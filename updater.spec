# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build for the standalone Windows updater."""

from app.version import APP_NAME

analysis = Analysis(
    ["updater_main.py"],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest", "PyInstaller", "tkinter"],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(analysis.pure)

updater_exe = EXE(
    pyz,
    analysis.scripts,
    analysis.binaries,
    analysis.datas,
    [],
    name=f"{APP_NAME} Updater",
    icon="assets/app_icon.ico",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
