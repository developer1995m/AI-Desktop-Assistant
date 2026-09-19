"""تنظیمات مشترک تست‌ها."""

import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


@pytest.fixture(autouse=True)
def no_blocking_message_boxes(monkeypatch):
    """پنجره‌های پیام مسدودکننده را در تست‌ها به فراخوان ثبت‌کننده تبدیل می‌کند.

    بدون این کار، اگر مسیری در برنامه به‌طور ناخواسته پنجره پیام باز کند،
    تست تا ابد منتظر کلیک کاربر می‌ماند و به‌جای خطا، هنگ می‌کند.
    تستی که رفتار پنجره را می‌سنجد، خودش بازنویسی می‌کند و بازنویسی آن مقدم است.
    """
    from PySide6.QtWidgets import QMessageBox

    shown: list[tuple[str, str]] = []

    def _record(kind):
        def _stub(*args, **kwargs):
            message = kwargs.get("text") or (args[2] if len(args) > 2 else "")
            shown.append((kind, str(message)))
            return QMessageBox.StandardButton.Ok

        return staticmethod(_stub)

    for kind in ("warning", "critical", "information", "about"):
        monkeypatch.setattr(QMessageBox, kind, _record(kind), raising=False)

    return shown


@pytest.fixture(scope="session")
def qt_app():
    """یک نمونه QApplication مشترک برای تست‌های رابط کاربری فراهم می‌کند."""
    application = QApplication.instance() or QApplication(sys.argv[:1])
    yield application


@pytest.fixture
def wait_for(qt_app):
    """منتظر می‌ماند تا شرطی برقرار شود و در این فاصله رویدادهای Qt را پردازش می‌کند."""

    def _wait(predicate, timeout: float = 5.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            qt_app.processEvents()
            if predicate():
                return True
            time.sleep(0.005)
        return predicate()

    return _wait
