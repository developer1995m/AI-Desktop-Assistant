# -*- mode: python ; coding: utf-8 -*-
"""فایل ساخت PyInstaller برای نسخه دسکتاپ ویندوز.

ساخت: .venv\\Scripts\\python.exe -m PyInstaller --noconfirm --clean ai_desktop_assistant.spec
خروجی: dist\\AI Desktop Assistant\\AI Desktop Assistant.exe
"""

from app.version import APP_NAME

analysis = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    # فقط آیکون برنامه بسته می‌شود؛ همان که پنجره، تسک‌بار و فایل exe از آن می‌خوانند.
    datas=[("assets/app_icon.ico", "assets")],
    # PyMuPDF و python-dotenv ماژول‌هایی دارند که PyInstaller خودکار تشخیص نمی‌دهد.
    # httpx2 هم در تابعی داخل کد import می‌شود (کلاینت بدون پروکسی سرویس‌های محلی).
    hiddenimports=["pymupdf", "dotenv", "openai", "httpx2"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest", "PyInstaller", "tkinter"],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(analysis.pure)

exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    icon="assets/app_icon.ico",
    version="version_info.txt",
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

collection = COLLECT(
    exe,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    name=APP_NAME,
)
