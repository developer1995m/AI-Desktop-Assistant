"""آیکون سینی سیستم برای یادآوری وظایف سررسیده.

یادآوری داخل برنامه کافی است تا وقتی کاربر پنجره را می‌بیند؛ ولی اگر پنجره زیر
پنجره‌های دیگر گم شود، اعلان سیستمی تنها راه رسیدن پیام است. این ماژول آن را
جدا نگه می‌دارد تا تست‌پذیر باشد و نبود سینی سیستم برنامه را نشکند.

نکته‌ای که با یک خطای واقعی کشف شد: ساختن `QSystemTrayIcon` روی سکویی که
سینی سیستم ندارد (مثل `offscreen` یا ویندوز سرور) باعث خطای دسترسی در سطح
حافظه می‌شود، نه استثنای پایتون. پس تنها زمانی ساخته می‌شود که خود Qt بگوید
سینی سیستم در دسترس است؛ برای تست، شیء سینی تزریق می‌شود.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

NOTIFICATION_TITLE = "یادآوری وظایف"
NOTIFICATION_DURATION_MS = 8000


class ReminderTray(QObject):
    """آیکون سینی سیستم با منوی میانبر و اعلان یادآوری.

    اعلان تکراری نمایش داده نمی‌شود: تایمر هر ربع ساعت یک‌بار بررسی می‌کند و
    بدون این محافظ، کاربر هر ربع ساعت یک اعلان یکسان می‌دید.
    """

    def __init__(
        self,
        icon: QIcon,
        *,
        on_open_window: Callable[[], None],
        on_open_tasks: Callable[[], None],
        on_quit: Callable[[], None],
        disabled: bool = False,
        tray_factory: Callable[[QIcon, QObject], object] | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)

        self._last_summary = ""
        self.tray: QSystemTrayIcon | object | None = None

        # تزریق شیء سینی فقط برای تست است؛ در برنامه همیشه خود Qt ساخته می‌شود
        # و آن هم فقط وقتی سینی سیستم واقعاً در دسترس باشد.
        #
        # پرسیدن از Qt بدون QApplication باعث خطای دسترسی در سطح حافظه می‌شود
        # (با یک اجرای واقعی دیدم)، پس اول همان را بررسی می‌کنیم.
        if tray_factory is None:
            self.available = (
                False
                if disabled or QApplication.instance() is None
                else QSystemTrayIcon.isSystemTrayAvailable()
            )
        else:
            self.available = not disabled

        if not self.available:
            return

        self.tray = (
            tray_factory(icon, self) if tray_factory is not None else QSystemTrayIcon(icon, self)
        )
        self.tray.setToolTip(NOTIFICATION_TITLE)

        menu = QMenu()
        menu.addAction("نمایش پنجره", on_open_window)
        menu.addAction("باز کردن وظایف", on_open_tasks)
        menu.addSeparator()
        menu.addAction("خروج", on_quit)

        self.tray.setContextMenu(menu)
        self.tray.activated.connect(
            lambda reason: on_open_window()
            if reason == QSystemTrayIcon.ActivationReason.DoubleClick
            else None
        )
        self.tray.show()

    def notify(self, summary: str) -> bool:
        """خلاصه یادآوری را به‌صورت اعلان سیستمی نشان می‌دهد.

        اگر سینی سیستم نبود یا همین متن قبلاً اعلان شده بود، `False` برمی‌گردد
        (یعنی اعلانی نمایش داده نشد).
        """
        text = (summary or "").strip()

        if not text:
            # چیزی برای یادآوری نیست؛ دفعه بعد باید بتوانیم دوباره اعلان دهیم.
            self._last_summary = ""
            return False

        if self.tray is None:
            return False

        if text == self._last_summary:
            # همین متن قبلاً اعلان شده؛ تکرارش فقط مزاحم است.
            return False

        self._last_summary = text
        self.tray.showMessage(
            NOTIFICATION_TITLE,
            text,
            QSystemTrayIcon.MessageIcon.Information,
            NOTIFICATION_DURATION_MS,
        )
        return True

    def hide(self) -> None:
        """آیکون را از سینی سیستم برمی‌دارد (هنگام خروج برنامه)."""
        self._last_summary = ""

        if self.tray is not None:
            self.tray.hide()
