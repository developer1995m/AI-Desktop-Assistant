"""ذخیره وضعیت رابط کاربری بین اجراهای برنامه.

اندازه و جای پنجره در یک فایل JSON کوچک نگه داشته می‌شود تا کاربر هر بار مجبور
نباشد پنجره را دوباره اندازه کند. مقادیر نامعتبر (مثلاً پنجره‌ای که از صفحه بیرون
افتاده) نادیده گرفته می‌شوند تا برنامه همیشه با پنجره‌ای قابل استفاده باز شود.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.services.paths import ui_state_path as default_ui_state_path

DEFAULT_WIDTH = 1100
DEFAULT_HEIGHT = 700
MIN_WIDTH = 800
MIN_HEIGHT = 500
MAX_WIDTH = 10000
MAX_HEIGHT = 10000
DEFAULT_THEME = "dark"


class UiStateStore:
    """خواندن و نوشتن وضعیت رابط کاربری در فایل JSON."""

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path is not None else default_ui_state_path()

    def read(self) -> dict[str, Any]:
        """محتوای فایل وضعیت را برمی‌گرداند.

        فایل نبود، JSON نامعتبر بود یا ساختارش دیکشنری نبود یعنی «وضعیت ذخیره‌شده‌ای
        نداریم»؛ در هر سه حالت دیکشنری خالی برگردانده می‌شود و برنامه با پیش‌فرض
        خودش بالا می‌آید.
        """
        if not self.path.is_file():
            return {}

        try:
            content = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

        return content if isinstance(content, dict) else {}

    def write(self, values: dict[str, Any]) -> bool:
        """وضعیت را ذخیره می‌کند و می‌گوید آیا نوشتن موفق بود.

        نوشتن وضعیت رابط کاربری هرگز نباید جلوی بسته‌شدن برنامه را بگیرد، پس خطای
        آن جذب و به شکل مقدار برگشتی گزارش می‌شود.
        """
        content = {**self.read(), **values}

        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps(content, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError:
            return False

        return True

    def window_geometry(self) -> tuple[int, int, int, int] | None:
        """اندازه و جای ذخیره‌شده پنجره را به‌صورت `(x, y, width, height)` می‌دهد.

        اگر مقدار ذخیره‌شده ناقص یا نامعتبر باشد «None» برگردانده می‌شود تا اندازه
        پیش‌فرض برنامه استفاده شود.
        """
        window = self.read().get("window")
        if not isinstance(window, dict):
            return None

        numbers: list[int] = []
        for key in ("x", "y", "width", "height"):
            value = window.get(key)
            if not isinstance(value, int) or isinstance(value, bool):
                return None
            numbers.append(value)

        x, y, width, height = numbers

        if not MIN_WIDTH <= width <= MAX_WIDTH or not MIN_HEIGHT <= height <= MAX_HEIGHT:
            return None

        return x, y, width, height

    def is_maximized(self) -> bool:
        """آیا پنجره دفعه قبل بیشینه‌شده بسته شد؟"""
        window = self.read().get("window")
        return bool(isinstance(window, dict) and window.get("maximized"))

    def save_window(
        self,
        x: int,
        y: int,
        width: int,
        height: int,
        *,
        maximized: bool = False,
    ) -> bool:
        """اندازه، جای پنجره و حالت بیشینه را ذخیره می‌کند."""
        return self.write(
            {
                "window": {
                    "x": int(x),
                    "y": int(y),
                    "width": int(width),
                    "height": int(height),
                    "maximized": bool(maximized),
                }
            }
        )

    def theme(self) -> str:
        """تم ذخیره‌شده را برمی‌گرداند؛ مقدار نامعتبر یعنی تم تیره."""
        from app.ui.theme import normalise_theme

        return normalise_theme(self.read().get("theme"))

    def save_theme(self, theme: str) -> bool:
        """انتخاب تم کاربر را ذخیره می‌کند."""
        from app.ui.theme import normalise_theme

        return self.write({"theme": normalise_theme(theme)})
