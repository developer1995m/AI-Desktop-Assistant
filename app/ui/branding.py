"""بارگذاری آیکون برنامه از پوشه منابع.

آیکون در `assets/app_icon.ico` نگه داشته می‌شود (هم برای پنجره و تسک‌بار و هم برای
`exe`)؛ همین فایل با `tools/make_icon.py` ساخته می‌شود. اگر فایل نبود، یک آیکون
خالی برگردانده می‌شود تا نبود آیکون هرگز اجرای برنامه را متوقف نکند.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QIcon

from app.services.paths import resource_dir

ICON_FILE_NAME = "app_icon.ico"


def icon_path() -> Path:
    """مسیر فایل آیکون برنامه."""
    return resource_dir() / ICON_FILE_NAME


def load_app_icon() -> QIcon:
    """آیکون برنامه را برمی‌گرداند؛ در نبود فایل، آیکون خالی."""
    path = icon_path()

    if not path.is_file():
        return QIcon()

    return QIcon(str(path))
