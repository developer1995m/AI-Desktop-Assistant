"""مسیرهای نوشتنی برنامه؛ یکسان برای اجرای معمولی و نسخه بسته‌بندی‌شده."""

from __future__ import annotations

import os
import sys
from pathlib import Path

APPLICATION_FOLDER = "AI Desktop Assistant"
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def is_frozen() -> bool:
    """آیا برنامه به‌صورت بسته‌بندی‌شده (PyInstaller) اجرا می‌شود؟"""
    return bool(getattr(sys, "frozen", False))


def user_data_dir() -> Path:
    """پوشه نوشتنی برنامه برای پایگاه‌داده و تنظیمات.

    در اجرای معمولی همان ریشه پروژه است تا توسعه ساده بماند؛ در نسخه
    بسته‌بندی‌شده پوشه برنامه ممکن است فقط‌خواندنی باشد، پس از مسیر داده کاربر
    سیستم‌عامل استفاده می‌شود.
    """
    if not is_frozen():
        return PROJECT_ROOT

    base = os.environ.get("APPDATA")

    if base:
        return Path(base) / APPLICATION_FOLDER

    # لینوکس و مک معادل مسیر داده کاربر را دارند.
    xdg_data_home = os.environ.get("XDG_DATA_HOME")
    if xdg_data_home:
        return Path(xdg_data_home) / APPLICATION_FOLDER

    return Path.home() / ".local" / "share" / APPLICATION_FOLDER


def database_path() -> Path:
    """مسیر پیش‌فرض پایگاه‌داده SQLite."""
    return user_data_dir() / "data" / "assistant.db"


def env_path() -> Path:
    """مسیر پیش‌فرض فایل تنظیمات `.env`."""
    return user_data_dir() / ".env"


def ui_state_path() -> Path:
    """مسیر فایل ذخیره وضعیت رابط کاربری (اندازه و جای پنجره)."""
    return user_data_dir() / "data" / "ui_state.json"


def resource_dir() -> Path:
    """پوشه منابع فقط‌خواندنی برنامه مثل آیکون.

    در نسخه بسته‌بندی‌شده، PyInstaller منابع را در پوشه موقت خودش باز می‌کند؛
    در اجرای معمولی همان پوشه `assets` کنار پروژه است.
    """
    if is_frozen():
        bundled = getattr(sys, "_MEIPASS", None)
        if bundled:
            return Path(bundled) / "assets"

    return PROJECT_ROOT / "assets"
