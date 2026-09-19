"""کارگرهای پس‌زمینه مشترک صفحه‌ها (گفتگو، پرسش از PDF و تست اتصال)."""

from __future__ import annotations

import threading

from PySide6.QtCore import QThread, Signal

from app.services.chat_service import ChatService, describe_error


class ChatStreamWorker(QThread):
    """درخواست به مدل را در رشته‌ای جداگانه اجرا می‌کند تا رابط کاربری متوقف نشود."""

    chunk_received = Signal(str)
    failed = Signal(str)

    def __init__(
        self,
        service: ChatService,
        history: list[dict[str, str]],
        prompt: str,
        memories: list[str] | None = None,
        system_prompt: str | None = None,
    ) -> None:
        super().__init__()

        self._service = service
        self._history = list(history)
        self._prompt = prompt
        # حافظه‌ها پیش از شروع رشته خوانده می‌شوند؛ اتصال SQLite بین رشته‌ها قابل استفاده نیست.
        self._memories = list(memories or [])
        self._system_prompt = system_prompt
        self._stop_event = threading.Event()

    def request_stop(self) -> None:
        """از رشته اصلی علامت توقف درخواست جاری را می‌دهد."""
        self._stop_event.set()

    def run(self) -> None:
        """درخواست را ارسال می‌کند و تکه‌های پاسخ را به رابط کاربری می‌فرستد."""
        try:
            stream = self._service.stream_reply(
                self._history,
                self._prompt,
                should_stop=self._stop_event.is_set,
                memories=self._memories,
                system_prompt=self._system_prompt,
            )
            for chunk in stream:
                self.chunk_received.emit(chunk)
        except Exception as error:  # noqa: BLE001 - همه خطاها به پیام کاربر تبدیل می‌شوند
            # اگر کاربر خودش درخواست را متوقف کرده باشد، خطای بعدی (مثلاً پایان مهلت
            # خواندن سوکت) نتیجه همان توقف است، نه یک مشکل واقعی.
            if self._stop_event.is_set():
                return

            # پیام خام SDK انگلیسی است و برای کاربر معنا ندارد؛ describe_error آن را
            # به یک راهنمای فارسی قابل‌فهم دسته‌بندی می‌کند.
            self.failed.emit(describe_error(error))


class ConnectionTestWorker(QThread):
    """بررسی اتصال به سرویس مدل را بیرون از رشته رابط کاربری انجام می‌دهد.

    تست اتصال ممکن است چند ثانیه طول بکشد؛ اگر در رشته رابط انجام شود پنجره در
    همین مدت بی‌پاسخ می‌شود.
    """

    succeeded = Signal(str)
    failed = Signal(str)

    def __init__(self, service: ChatService, parent: QThread | None = None) -> None:
        super().__init__(parent)
        self._service = service

    def run(self) -> None:
        """اتصال را بررسی می‌کند و نتیجه را گزارش می‌دهد."""
        try:
            self.succeeded.emit(self._service.check_connection())
        except Exception as error:  # noqa: BLE001 - همه خطاها به پیام کاربر تبدیل می‌شوند
            self.failed.emit(describe_error(error))
