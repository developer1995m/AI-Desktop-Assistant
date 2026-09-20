"""نقطه شروع برنامه AI Desktop Assistant."""

from __future__ import annotations

import sys
import tempfile
import os
from contextlib import contextmanager
from pathlib import Path
from collections.abc import Iterator

from PySide6.QtWidgets import QApplication

from app.services import pdf_service
from app.services.pdf_service import load_pdf
from app.services.settings import AppSettings, KNOWN_VARIABLES
from app.services.storage import ConversationStore
from app.services.ui_state import UiStateStore
from app.version import APP_NAME, APP_VERSION
from app.ui.branding import load_app_icon
from app.ui.main_window import MainWindow

SELF_CHECK_FLAG = "--self-check"


@contextmanager
def _isolated_self_check_environment() -> Iterator[None]:
    """متغیرهای تنظیمات کاربر را فقط برای طول self-check نادیده می‌گیرد."""
    saved = {name: os.environ.get(name) for name in KNOWN_VARIABLES}
    try:
        for name in KNOWN_VARIABLES:
            os.environ.pop(name, None)
        yield
    finally:
        for name, value in saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def _report(message: str, *, error: bool = False) -> None:
    """چاپ پیام خودآزمایی؛ در نسخه پنجره‌ای (بدون کنسول) بی‌صدا نادیده گرفته می‌شود."""
    stream = sys.stderr if error else sys.stdout

    if stream is None:
        return

    try:
        print(message, file=stream)
    except (OSError, ValueError):  # pragma: no cover - فقط در نسخه بدون کنسول
        pass


def run_self_check(application: QApplication) -> int:
    """بدون نمایش پنجره، اجزای کلیدی برنامه را بررسی می‌کند.

    این حالت برای بررسی سلامت ساخت (CI و نسخه بسته‌بندی‌شده) استفاده می‌شود:
    ساخت پنجره، ساخت صفحات و خواندن یک PDF که همین‌جا با PyMuPDF ساخته می‌شود.
    """
    problems: list[str] = []

    with tempfile.TemporaryDirectory() as folder, _isolated_self_check_environment():
        root = Path(folder)
        window = MainWindow(
            chat_store=ConversationStore(root / "data" / "assistant.db"),
            ui_state=UiStateStore(root / "data" / "ui_state.json"),
            settings=AppSettings(root / ".env"),
        )
        application.processEvents()

        if window.page_stack.count() != len(window.page_indexes):
            problems.append("همه صفحات در پنجره ساخته نشدند.")

        if window.windowIcon().isNull():
            problems.append("آیکون برنامه بارگذاری نشد.")

        # بنر راه‌اندازی اولیه باید دقیقاً برعکس وضعیت کلید API دیده شود.
        banner_visible = window.chat_page.setup_banner.isVisibleTo(window.chat_page)
        if banner_visible == window.chat_service.is_configured():
            problems.append("بنر راه‌اندازی اولیه با وضعیت کلید API هم‌خوان نیست.")

        sidebar_keys = {item[0] for item in window.sidebar.NAVIGATION_ITEMS}
        if set(window.page_indexes) != sidebar_keys:
            problems.append("نشانی صفحات با آیتم‌های سایدبار هم‌خوان نیست.")

        pdf_path = Path(folder) / "self-check.pdf"
        second_path = Path(folder) / "self-check-two.pdf"

        try:
            for target, marker in (
                (pdf_path, "self check marker"),
                (second_path, "second self check marker"),
            ):
                document = pdf_service.fitz.open()
                page = document.new_page()
                page.insert_text((72, 96), marker, fontsize=12)
                document.save(target)
                document.close()

            extracted = load_pdf(pdf_path)

            if "self check marker" not in extracted.text:
                problems.append("متن PDF درست استخراج نشد.")

            # مسیر چندسندی: باز نگه‌داشتن دو سند و ساخت پرامپت مشترک.
            if not window.pdf_page.load_document(str(pdf_path)):
                problems.append("صفحه PDF نتوانست سند اول را باز کند.")
            if not window.pdf_page.load_document(str(second_path)):
                problems.append("صفحه PDF نتوانست سند دوم را باز کند.")

            open_documents = window.pdf_page.documents
            if len(open_documents) != 2:
                problems.append("صفحه PDF هر دو سند را باز نگه نداشت.")

            prompt = pdf_service.documents_system_prompt(
                open_documents, question="self check marker"
            )
            for name in ("self-check.pdf", "self-check-two.pdf"):
                if name not in prompt:
                    problems.append(f"پرامپت چندسندی نام «{name}» را شامل نشد.")
        except Exception as error:  # noqa: BLE001 - هر خطایی یعنی ساخت ناسالم است
            problems.append(f"خواندن PDF ممکن نبود: {error}")

        window.close()
        application.processEvents()

    for problem in problems:
        _report(f"self-check: {problem}", error=True)

    _report("self-check: FAILED" if problems else "self-check: OK")

    return 1 if problems else 0


def main(argv: list[str] | None = None) -> int:
    """برنامه را اجرا می‌کند و کد خروج را برمی‌گرداند."""
    arguments = list(sys.argv[1:] if argv is None else argv)

    application = QApplication.instance() or QApplication(sys.argv)
    application.setApplicationName(APP_NAME)
    application.setApplicationVersion(APP_VERSION)
    application.setOrganizationName(APP_NAME)
    application.setWindowIcon(load_app_icon())

    if SELF_CHECK_FLAG in arguments:
        return run_self_check(application)

    window = MainWindow()
    window.show()

    return application.exec()


if __name__ == "__main__":
    sys.exit(main())
