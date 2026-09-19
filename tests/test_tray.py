"""تست‌های آیکون سینی سیستم و اعلان یادآوری.

این تست‌ها عمداً `QSystemTrayIcon` واقعی نمی‌سازند: روی سکویی که سینی سیستم
ندارد (مثل `offscreen`) ساختن آن خطای دسترسی می‌دهد. به‌جایش یک سینی ساختگی
تزریق می‌شود تا منطق منو، اعلان و بی‌تکراربودن بررسی شود.
"""

from datetime import date

from PySide6.QtGui import QIcon

from app.services.storage import ConversationStore
from app.ui.tray import NOTIFICATION_TITLE, ReminderTray

from tests.test_main_window import make_window


class FakeTray:
    """سینی سیستم ساختگی: پیام‌ها و وضعیت را ثبت می‌کند."""

    class _Signal:
        def __init__(self) -> None:
            self.slots: list = []

        def connect(self, slot) -> None:
            self.slots.append(slot)

        def emit(self, reason) -> None:
            for slot in self.slots:
                slot(reason)

    def __init__(self, icon=None, parent=None) -> None:
        self.messages: list[tuple[str, str, int]] = []
        self.tooltip = ""
        self.menu = None
        self.shown = 0
        self.hidden = 0
        self.activated = FakeTray._Signal()

    def setToolTip(self, text: str) -> None:
        self.tooltip = text

    def setContextMenu(self, menu) -> None:
        self.menu = menu

    def show(self) -> None:
        self.shown += 1

    def hide(self) -> None:
        self.hidden += 1

    def showMessage(self, title: str, text: str, icon=None, duration: int = 0) -> None:
        self.messages.append((title, text, duration))


def make_tray(*, disabled: bool = False, factory=None) -> tuple[ReminderTray, dict]:
    calls: dict[str, int] = {"window": 0, "tasks": 0, "quit": 0}
    tray = ReminderTray(
        QIcon(),
        on_open_window=lambda: calls.__setitem__("window", calls["window"] + 1),
        on_open_tasks=lambda: calls.__setitem__("tasks", calls["tasks"] + 1),
        on_quit=lambda: calls.__setitem__("quit", calls["quit"] + 1),
        disabled=disabled,
        tray_factory=factory,
    )
    return tray, calls


# ------------------------------------------------------------- بدون سینی سیستم


def test_tray_without_system_support_stays_dormant():
    tray, _calls = make_tray(disabled=True)

    assert tray.available is False
    assert tray.tray is None
    assert tray.notify("۱ وظیفه امروز موعد دارد.") is False

    # پنهان‌کردن هم نباید خطا بدهد.
    tray.hide()


def test_availability_is_taken_from_the_platform_when_not_injected(qt_app):
    """در برنامه واقعی، تصمیم ساخت سینی با خود Qt است نه با ما."""
    from PySide6.QtWidgets import QSystemTrayIcon

    tray, _calls = make_tray()

    assert tray.available == QSystemTrayIcon.isSystemTrayAvailable()
    assert (tray.tray is None) == (not tray.available)


def test_without_a_qt_application_no_tray_is_attempted(monkeypatch):
    """بدون QApplication نباید به Qt مراجعه کرد.

    پرسیدن وضعیت سینی از Qt در این حالت روی ویندوز خطای دسترسی می‌دهد، پس
    برنامه باید بی‌صدا از سینی صرف‌نظر کند.
    """
    from PySide6.QtWidgets import QApplication, QSystemTrayIcon

    probed: list[bool] = []
    monkeypatch.setattr(QApplication, "instance", staticmethod(lambda: None))
    monkeypatch.setattr(
        QSystemTrayIcon,
        "isSystemTrayAvailable",
        staticmethod(lambda: probed.append(True) or True),
    )

    tray, _calls = make_tray()

    assert probed == []
    assert tray.available is False
    assert tray.tray is None


# --------------------------------------------------------------- سینی در دسترس


def test_tray_has_a_menu_with_the_three_actions():
    tray, calls = make_tray(factory=FakeTray)
    fake = tray.tray

    assert isinstance(fake, FakeTray)
    assert fake.tooltip == NOTIFICATION_TITLE
    assert fake.shown == 1

    action_names = [action.text() for action in fake.menu.actions() if action.text()]
    assert action_names == ["نمایش پنجره", "باز کردن وظایف", "خروج"]

    for action in fake.menu.actions():
        if action.text():
            action.trigger()

    assert calls == {"window": 1, "tasks": 1, "quit": 1}


def test_double_clicking_the_tray_icon_shows_the_window():
    from PySide6.QtWidgets import QSystemTrayIcon

    tray, calls = make_tray(factory=FakeTray)
    fake = tray.tray

    fake.activated.emit(QSystemTrayIcon.ActivationReason.Trigger)
    assert calls["window"] == 0

    fake.activated.emit(QSystemTrayIcon.ActivationReason.DoubleClick)
    assert calls["window"] == 1


def test_notification_uses_the_reminder_summary():
    tray, _calls = make_tray(factory=FakeTray)

    assert tray.notify("۲ وظیفه موعدش گذشته") is True
    assert tray.tray.messages == [
        (NOTIFICATION_TITLE, "۲ وظیفه موعدش گذشته", 8000)
    ]


def test_the_same_reminder_is_not_repeated():
    tray, _calls = make_tray(factory=FakeTray)

    assert tray.notify("1 وظیفه امروز موعد دارد.") is True
    assert tray.notify("1 وظیفه امروز موعد دارد.") is False

    # متن دیگری دوباره اعلان می‌گیرد.
    assert tray.notify("3 وظیفه موعدش گذشته") is True

    # و وقتی چیزی برای یادآوری نیست، یادآوری قبلی از نو اعلان می‌شود.
    assert tray.notify("") is False
    assert tray.notify("1 وظیفه امروز موعد دارد.") is True

    assert [text for _title, text, _duration in tray.tray.messages] == [
        "1 وظیفه امروز موعد دارد.",
        "3 وظیفه موعدش گذشته",
        "1 وظیفه امروز موعد دارد.",
    ]


def test_empty_summary_is_never_notified():
    tray, _calls = make_tray(factory=FakeTray)

    assert tray.notify("   ") is False
    assert tray.tray.messages == []


def test_hide_removes_the_icon_and_resets_the_dedup_memory():
    tray, _calls = make_tray(factory=FakeTray)

    tray.notify("یادآوری")
    tray.hide()

    assert tray.tray.hidden == 1
    assert tray.notify("یادآوری") is True


# ------------------------------------------------------------- اتصال به پنجره


def test_window_does_not_notify_while_user_is_looking_at_it(qt_app, tmp_path, monkeypatch):
    store = ConversationStore(tmp_path / "chat.db")
    window = make_window(qt_app, tmp_path, monkeypatch, store=store)
    notified: list[str] = []
    monkeypatch.setattr(window.reminder_tray, "notify", notified.append)

    # کاربر پنجره را در پیش‌زمینه دارد: چیپ سربرگ کافی است.
    monkeypatch.setattr(type(window), "isActiveWindow", lambda self: True)
    window.check_task_reminders(quiet=True)
    assert notified == []

    # پنجره در پیش‌زمینه نیست: اعلان سیستمی می‌آید.
    monkeypatch.setattr(type(window), "isActiveWindow", lambda self: False)
    store.create_task("امروزی", "normal", due_date=date.today().isoformat())
    window.check_task_reminders(quiet=True)
    assert notified == ["1 وظیفه امروز موعد دارد."]

    window.close()


def test_reminder_signal_reaches_the_tray(qt_app, tmp_path, monkeypatch):
    """سیگنال یادآوری باید به مسیر اعلان وصل باشد، نه فقط به تست‌ها."""
    store = ConversationStore(tmp_path / "chat.db")
    window = make_window(qt_app, tmp_path, monkeypatch, store=store)
    received: list[str] = []
    monkeypatch.setattr(window.reminder_tray, "notify", received.append)
    monkeypatch.setattr(type(window), "isActiveWindow", lambda self: False)

    window.reminder_triggered.emit("خلاصه آزمایشی")

    assert received == ["خلاصه آزمایشی"]

    window.close()
