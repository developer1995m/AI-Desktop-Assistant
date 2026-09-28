"""صفحه گفتگو با هوش مصنوعی."""

from __future__ import annotations

import shiboken6 as shiboken2
import sqlite3
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.services.chat_service import MAX_HISTORY_MESSAGES, ChatService
from app.services.storage import ConversationStore
from app.services.voice_service import VoiceService
from app.ui.widgets.chat_bubble import MessageBubble
from app.ui.widgets.chat_input import ChatInput
from app.ui.workers import ChatStreamWorker

EMPTY_STATE_TEXT = (
    "پیام خود را بنویسید تا گفتگو شروع شود.\n"
    "پاسخ مدل به‌صورت زنده در همین صفحه نمایش داده می‌شود."
)
STREAM_PLACEHOLDER = "…"
FLUSH_INTERVAL_MS = 60
SETUP_TITLE = "کلید API تنظیم نشده است"
SETUP_HINT = (
    "بدون کلید API گفتگو کار نمی‌کند. کلید را از حساب سرویس خود بردارید و در "
    "صفحه تنظیمات ذخیره کنید؛ همان لحظه فعال می‌شود."
)


class ChatPage(QWidget):
    """صفحه گفتگو با هوش مصنوعی، نمایش جریانی پاسخ و لغو درخواست."""

    conversations_updated = Signal()
    open_settings_requested = Signal()

    def __init__(
        self,
        service: ChatService,
        store: ConversationStore,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)

        self.setObjectName("chatPage")

        self._service = service
        self._store = store
        self._conversation_id: int | None = None
        self._history: list[dict[str, str]] = []
        self._message_rows: list[QWidget] = []
        self._worker: ChatStreamWorker | None = None
        self._streaming_bubble: MessageBubble | None = None
        self._generation = 0
        self._pending_text = ""
        self._response_text = ""
        self._stream_failed = False
        self._stop_requested = False
        self._is_busy = False

        self._flush_timer = QTimer(self)
        self._flush_timer.setInterval(FLUSH_INTERVAL_MS)
        self._flush_timer.timeout.connect(self._flush_pending_text)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 24, 32, 24)
        layout.setSpacing(14)
        layout.addWidget(self._create_toolbar())
        layout.addWidget(self._create_setup_banner())
        layout.addWidget(self._create_transcript(), 1)

        self.history_label = QLabel()
        self.history_label.setObjectName("chatStatus")
        self.history_label.setWordWrap(True)
        self.history_label.setVisible(False)
        layout.addWidget(self.history_label)

        self.status_label = QLabel()
        self.status_label.setObjectName("chatStatus")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        layout.addWidget(self._create_composer())

        self.reload_configuration()
        self.restore_last_conversation()

    # ------------------------------------------------------------------ ساخت رابط

    def _create_toolbar(self) -> QWidget:
        """نوار بالای صفحه شامل عنوان، مدل فعال و دکمه پاک‌کردن گفتگو."""
        toolbar = QWidget()
        toolbar.setObjectName("chatToolbar")

        layout = QVBoxLayout(toolbar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(12)

        title_label = QLabel("گفتگو با هوش مصنوعی")
        title_label.setObjectName("pageTitle")
        title_label.setWordWrap(True)

        self.model_label = QLabel()
        self.model_label.setObjectName("modelChip")

        self.memory_label = QLabel()
        self.memory_label.setObjectName("memoryChip")
        self.memory_label.setVisible(False)

        self.clear_button = QPushButton("گفتگوی جدید")
        self.clear_button.setObjectName("ghostButton")
        self.clear_button.clicked.connect(self.clear_conversation)

        self.export_button = QPushButton("خروجی")
        self.export_button.setObjectName("ghostButton")
        self.export_button.setToolTip("ذخیره این گفتگو در یک فایل Markdown")
        self.export_button.clicked.connect(self.export_markdown)

        title_row.addWidget(title_label, 1)
        title_row.addWidget(self.model_label)
        title_row.addWidget(self.memory_label)
        layout.addLayout(title_row)

        actions_row = QHBoxLayout()
        actions_row.setContentsMargins(0, 0, 0, 0)
        actions_row.setSpacing(10)
        actions_row.addStretch(1)
        actions_row.addWidget(self.export_button)
        actions_row.addWidget(self.clear_button)
        layout.addLayout(actions_row)

        return toolbar

    def _create_setup_banner(self) -> QFrame:
        """راهنمای راه‌اندازی اولیه را می‌سازد.

        تا وقتی کلید API تنظیم نشده، کاربر پیش از نوشتن پیام می‌بیند چه چیزی کم است و
        یک دکمه مستقیم به صفحه تنظیمات دارد؛ اینطور به جای حباب خطا پس از اولین
        ارسال، مسیر درست از همان ابتدا جلوی چشم است.
        """
        banner = QFrame()
        banner.setObjectName("setupBanner")

        layout = QHBoxLayout(banner)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(14)

        text_column = QWidget()
        text_layout = QVBoxLayout(text_column)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(3)

        self.setup_title_label = QLabel(SETUP_TITLE)
        self.setup_title_label.setObjectName("setupBannerTitle")

        self.setup_hint_label = QLabel(SETUP_HINT)
        self.setup_hint_label.setObjectName("setupBannerText")
        self.setup_hint_label.setWordWrap(True)

        text_layout.addWidget(self.setup_title_label)
        text_layout.addWidget(self.setup_hint_label)

        self.setup_button = QPushButton("باز کردن تنظیمات")
        self.setup_button.setObjectName("primaryButton")
        self.setup_button.setFixedHeight(34)
        self.setup_button.clicked.connect(self.open_settings_requested.emit)

        layout.addWidget(text_column, 1)
        layout.addWidget(self.setup_button, 0, Qt.AlignmentFlag.AlignBottom)

        self.setup_banner = banner
        return banner

    def _create_transcript(self) -> QScrollArea:
        """ناحیه اسکرول‌شونده پیام‌ها را می‌سازد."""
        self.transcript_container = QWidget()
        self.transcript_container.setObjectName("transcriptContainer")

        self.message_layout = QVBoxLayout(self.transcript_container)
        self.message_layout.setContentsMargins(4, 4, 4, 4)
        self.message_layout.setSpacing(12)

        self.empty_state_label = QLabel(EMPTY_STATE_TEXT)
        self.empty_state_label.setObjectName("emptyState")
        self.empty_state_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_state_label.setWordWrap(True)
        self.message_layout.addWidget(self.empty_state_label)
        self.message_layout.addStretch(1)

        self.scroll_area = QScrollArea()
        self.scroll_area.setObjectName("transcript")
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll_area.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.scroll_area.setWidget(self.transcript_container)

        return self.scroll_area

    def _create_composer(self) -> QWidget:
        """کادر نوشتن پیام و دکمه ارسال را می‌سازد."""
        composer = QWidget()

        layout = QHBoxLayout(composer)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        self.chat_input = ChatInput()
        self.chat_input.send_requested.connect(self._submit_from_input)

        self.voice_button = QPushButton("🎙️")
        self.voice_button.setObjectName("ghostButton")
        self.voice_button.setFixedSize(44, 44)
        self.voice_button.setToolTip("انتخاب فایل صوتی و تبدیل آن به متن")
        self.voice_button.clicked.connect(self._handle_voice_input)

        self.send_button = QPushButton("ارسال")
        self.send_button.setObjectName("primaryButton")
        self.send_button.setFixedHeight(44)
        self.send_button.clicked.connect(self._handle_primary_clicked)

        layout.addWidget(self.chat_input, 1)
        layout.addWidget(self.voice_button, 0, Qt.AlignmentFlag.AlignBottom)
        layout.addWidget(self.send_button, 0, Qt.AlignmentFlag.AlignBottom)

        return composer

    # --------------------------------------------------------------------- تنظیمات

    def reload_configuration(self) -> None:
        """تنظیمات را دوباره می‌خواند و وضعیت آماده‌بودن سرویس را نشان می‌دهد."""
        self._service.reload_configuration()
        self.model_label.setText(f"مدل: {self._service.model}")
        self.refresh_memory_status()

        configured = self._service.is_configured()
        self.setup_banner.setVisible(not configured)

        if configured:
            self._set_status("آماده است — پیام خود را بنویسید و Enter بزنید.")
            self._update_history_hint()
        else:
            self._set_status(
                "کلید API تنظیم نشده است؛ از دکمه بالا یا صفحه تنظیمات مقدار "
                "OPENAI_API_KEY را وارد کنید."
            )

    def _update_history_hint(self) -> None:
        """شفافیت درباره تاریخچه: مدل چند پیام از این گفتگو می‌بیند؟

        فقط تعداد مشخصی پیام آخر به مدل فرستاده می‌شود؛ اگر گفتگو از این حد گذشت،
        کاربر باید بداند که پیام‌های قدیمی‌تر دیده نمی‌شوند.
        """
        usable = sum(
            1
            for message in self._history
            if message.get("role") in {"user", "assistant"} and message.get("content")
        )

        omitted = max(0, usable - MAX_HISTORY_MESSAGES)

        # تا وقتی چیزی کنار گذاشته نشده، هشدار معنا ندارد و فقط فضای گفتگو را
        # می‌گیرد؛ پس تازه وقتی گفتگو از پنجره تاریخچه گذشت ظاهر می‌شود.
        if not omitted:
            self.history_label.clear()
            self.history_label.setVisible(False)
            return

        self.history_label.setText(
            f"مدل حداکثر {MAX_HISTORY_MESSAGES} پیام آخر این گفتگو را می‌بیند؛ "
            f"{omitted} پیام قدیمی‌تر فعلاً کنار گذاشته می‌شود."
        )
        self.history_label.setVisible(True)

    def _active_memories(self) -> list[str]:
        """متن حافظه‌های فعال را می‌خواند.

        این متد باید در رشته رابط کاربری صدا زده شود؛ اتصال SQLite بین رشته‌ها
        قابل استفاده نیست، پس نتیجه پیش از شروع درخواست خوانده و به رشته کارگر
        پاس داده می‌شود. خواندن از پایگاه‌داده خود صفحه انجام می‌شود تا نتیجه به
        سیم‌کشی سرویس وابسته نباشد.
        """
        try:
            return [
                memory.content
                for memory in self._store.list_memories(only_enabled=True)
            ]
        except sqlite3.Error:
            return []

    def refresh_memory_status(self) -> None:
        """تعداد حافظه‌های فعال را در نوار وضعیت نشان می‌دهد."""
        count = len(self._active_memories())

        if count:
            self.memory_label.setText(f"حافظه فعال: {count}")
            self.memory_label.setVisible(True)
        else:
            self.memory_label.setText("")
            self.memory_label.setVisible(False)

    @property
    def is_busy(self) -> bool:
        """آیا درخواستی در حال اجراست؟"""
        return self._is_busy

    @property
    def current_conversation_id(self) -> int | None:
        """شناسه گفتگویی که در صفحه باز است."""
        return self._conversation_id

    def load_conversation(self, conversation_id: int) -> None:
        """یک گفتگوی ذخیره‌شده را در صفحه بارگذاری می‌کند."""
        if conversation_id == self._conversation_id:
            return

        try:
            messages = self._store.load_messages(conversation_id)
        except sqlite3.Error as error:
            self._set_status(f"بازکردن گفتگو ناموفق بود: {error}")
            return

        if self._worker is not None:
            self.shutdown()

        self._clear_transcript()
        self._set_busy(False)
        self._conversation_id = conversation_id

        for message in messages:
            self._history.append({"role": message["role"], "content": message["content"]})
            self._add_bubble(message["role"], message["content"])

        if messages:
            self._set_status("گفتگوی ذخیره‌شده بارگذاری شد.")

        self.conversations_updated.emit()

    def delete_conversation(self, conversation_id: int) -> None:
        """یک گفتگوی ذخیره‌شده را حذف می‌کند."""
        try:
            self._store.delete_conversation(conversation_id)
        except sqlite3.Error as error:
            self._set_status(f"حذف گفتگو ناموفق بود: {error}")
            return

        if conversation_id == self._conversation_id:
            self.clear_conversation()
            return

        self.conversations_updated.emit()

    def shutdown(self) -> None:
        """درخواست در حال اجرا را متوقف می‌کند تا برنامه بدون هشدار بسته شود."""
        worker = self._worker
        if worker is None:
            return

        worker.request_stop()
        worker.wait(2000)
        self._worker = None

    # ---------------------------------------------------------------------- ارسال

    def _submit_from_input(self) -> None:
        """ارسال پیام با Enter؛ در حین اجرای درخواست نادیده گرفته می‌شود."""
        if self._is_busy:
            return

        self._send(self.chat_input.take_text())

    def _handle_primary_clicked(self) -> None:
        """دکمه ارسال در حالت عادی پیام می‌فرستد و در حین پاسخ کار متوقف‌کننده دارد."""
        if self._is_busy:
            self._stop_streaming()
            return

        self._send(self.chat_input.take_text())

    def _handle_voice_input(self) -> None:
        """یک فایل صوتی انتخاب می‌کند و آن را به متن تبدیل می‌کند."""
        if self._is_busy:
            return

        path, _filter = QFileDialog.getOpenFileName(
            self,
            "انتخاب فایل صوتی",
            "",
            "Audio Files (*.wav *.mp3 *.m4a *.aac *.ogg *.flac);;All Files (*.*)",
        )

        if not path:
            return

        file_suffix = Path(path).suffix.lower()
        supported = {".wav", ".mp3", ".m4a", ".aac", ".ogg", ".flac"}
        if file_suffix not in supported:
            self._set_status("فقط فایل‌های صوتی با فرمت wav، mp3، m4a، aac، ogg و flac پشتیبانی می‌شوند.")
            return

        try:
            voice_service = VoiceService(self._service._settings)
            transcript = voice_service.transcribe_file(path)
        except Exception as error:  # noqa: BLE001 - نشان دادن پیام کاربر مهم‌تر از نوع خطا است.
            self._set_status(str(error))
            return

        current = self.chat_input.toPlainText().strip()
        if current:
            self.chat_input.setPlainText(f"{current}\n{transcript}")
        else:
            self.chat_input.setPlainText(transcript)

        self._set_status("متن صدا به ورودی گفتگو اضافه شد.")

    def _send(self, text: str) -> None:
        """پیام کاربر را نمایش می‌دهد و پاسخ مدل را به‌صورت جریانی دریافت می‌کند."""
        if not text:
            return

        self._add_bubble("user", text)
        self._history.append({"role": "user", "content": text})

        self._streaming_bubble = self._add_bubble("assistant", STREAM_PLACEHOLDER)
        self._pending_text = ""
        self._response_text = ""
        self._stream_failed = False
        self._stop_requested = False

        self._set_busy(True)
        self._set_status("در حال دریافت پاسخ…")

        generation = self._generation
        memories = self._active_memories()
        worker = ChatStreamWorker(self._service, list(self._history[:-1]), text, memories)
        worker.chunk_received.connect(lambda chunk, gen=generation: self._on_chunk(gen, chunk))
        worker.failed.connect(lambda message, gen=generation: self._on_failed(gen, message))
        worker.finished.connect(lambda gen=generation: self._on_worker_finished(gen))

        self._worker = worker
        worker.start()

    def _stop_streaming(self) -> None:
        """پاسخ در حال دریافت را متوقف می‌کند.

        توقف بین تکه‌های پاسخ اعمال می‌شود، پس ممکن است تا رسیدن تکه بعدی کمی طول بکشد؛
        پیام وضعیت همین را صادقانه می‌گوید و نتیجه نهایی پس از پایان رشته اعلام می‌شود.
        """
        worker = self._worker
        if worker is None:
            return

        self._stop_requested = True
        worker.request_stop()
        self._set_status("در حال توقف پاسخ…")

    def stop_response(self) -> None:
        """اگر پاسخی در حال دریافت باشد، آن را متوقف می‌کند."""
        if self._is_busy:
            self._stop_streaming()

    def _on_chunk(self, generation: int, chunk: str) -> None:
        """تکه‌های متن را بافر می‌کند تا رابط کاربری با تأخیر کوتاه به‌روز شود."""
        if generation != self._generation:
            return

        self._pending_text += chunk
        if not self._flush_timer.isActive():
            self._flush_timer.start()

    def _flush_pending_text(self) -> None:
        """متن بافرشده را یک‌باره در حباب پاسخ اضافه می‌کند."""
        if not self._pending_text:
            return

        chunk, self._pending_text = self._pending_text, ""
        bubble = self._streaming_bubble
        if bubble is None:
            return

        if not self._response_text:
            bubble.set_text("")

        self._response_text += chunk
        bubble.append_text(chunk)
        self._scroll_to_bottom()

    def _on_failed(self, generation: int, message: str) -> None:
        """خطا را در گفتگو نمایش می‌دهد."""
        if generation != self._generation:
            return

        self._stream_failed = True
        self._flush_timer.stop()
        self._pending_text = ""

        bubble = self._streaming_bubble
        if bubble is not None and not self._response_text.strip():
            bubble.role = "error"
            bubble.setObjectName("errorBubble")
            _repolish(bubble)
            bubble.set_text(message)
        else:
            self._add_bubble("error", message)

        self._set_status("ارسال درخواست ناموفق بود.")

    def _on_worker_finished(self, generation: int) -> None:
        """پس از پایان درخواست، وضعیت صفحه و تاریخچه گفتگو را به‌روز می‌کند."""
        if generation != self._generation or self._worker is None:
            return

        self._flush_timer.stop()
        self._flush_pending_text()
        self._streaming_bubble = None

        storage_error: str | None = None

        if self._stream_failed:
            # پیام ناموفق از تاریخچه حذف می‌شود تا ارسال دوباره تمیز باشد.
            self._history.pop()
        elif self._response_text.strip():
            self._history.append({"role": "assistant", "content": self._response_text})
            storage_error = self._persist_exchange()
        else:
            self._set_status("پاسخی از مدل دریافت نشد.")

        # شیء QThread به والد وصل نمیشود و deleteLater هم فراخوانی نمیگردد؛ تخریب آن به همراه
        # ویجت والد، پیش از پایان کامل رشته، باعث کرش سطح پایین Qt میشود. مرجع پایتون همینجا آزاد میشود.
        self._worker = None

        self._set_busy(False)

        if storage_error is not None:
            self._set_status(storage_error)
        elif self._stop_requested:
            self._set_status("پاسخ متوقف شد.")
        elif self._service.is_configured() and not self._stream_failed:
            self._set_status("آماده است — پیام خود را بنویسید و Enter بزنید.")

        self._update_history_hint()
        self._stop_requested = False

    # ----------------------------------------------------------------- ذخیره‌سازی

    def restore_last_conversation(self) -> None:
        """آخرین گفتگوی ذخیره‌شده را هنگام اجرای برنامه بازمی‌گرداند."""
        try:
            conversation = self._store.latest_conversation()
        except sqlite3.Error as error:
            self._set_status(f"خواندن گفتگوهای ذخیره‌شده ناموفق بود: {error}")
            return

        if conversation is None:
            return

        self.load_conversation(conversation.id)

    def _persist_exchange(self) -> str | None:
        """آخرین پیام کاربر و پاسخ مدل را ذخیره می‌کند و در صورت خطا پیام آن را برمی‌گرداند."""
        if len(self._history) < 2:
            return None

        user_message, assistant_message = self._history[-2], self._history[-1]
        if user_message["role"] != "user" or assistant_message["role"] != "assistant":
            return None

        is_new_conversation = self._conversation_id is None

        try:
            if is_new_conversation:
                self._conversation_id = self._store.create_conversation(
                    user_message["content"]
                )
            self._store.add_exchange(
                self._conversation_id,
                user_message["content"],
                assistant_message["content"],
            )
        except sqlite3.Error as error:
            return f"ذخیره گفتگو ناموفق بود: {error}"

        if is_new_conversation:
            self.conversations_updated.emit()

        return None

    # -------------------------------------------------------------------- خروجی

    def export_markdown(self) -> None:
        """گفتگوی جاری را در یک فایل Markdown ذخیره می‌کند."""
        if not self._history:
            self._set_status("گفتگویی برای خروجی گرفتن نیست.")
            return

        default_name = f"گفتگو-{datetime.now():%Y-%m-%d-%H%M}.md"
        path, _filter = QFileDialog.getSaveFileName(
            self,
            "ذخیره گفتگو",
            default_name,
            "Markdown (*.md)",
        )

        if not path:
            return

        target = Path(path)

        try:
            # پوشه انتخابی کاربر ممکن است هنوز ساخته نشده باشد؛
            # بی‌آنکه مسیر را زیر پا بگذاریم، فقط پوشه‌های نبوده را می‌سازیم.
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(self.markdown_transcript(), encoding="utf-8")
        except OSError as error:
            QMessageBox.warning(self, "خروجی گفتگو", f"ذخیره ناموفق بود: {error}")
            return

        self._set_status(f"گفتگو در {target.name} ذخیره شد.")

    def markdown_transcript(self) -> str:
        """گفتگوی جاری را به متن Markdown تبدیل می‌کند.

        پیام کاربر عنوان سطح‌سوم و پاسخ دستیار متن آزاد است تا فایل خوانا بماند؛
        خطاهای نمایش‌داده‌شده در فایل نمی‌آیند چون بخشی از گفتگو نیستند.
        """
        lines = [
            f"# گفتگو: {self._conversation_title()}",
            f"",
            f"*خروجی گرفته‌شده از AI Desktop Assistant در {datetime.now():%Y-%m-%d %H:%M}*",
            "",
        ]

        for message in self._history:
            if message.get("role") not in {"user", "assistant"}:
                continue

            content = str(message.get("content") or "").strip()

            if not content:
                continue

            if message["role"] == "user":
                lines.append(f"### شما\n\n{content}\n")
            else:
                lines.append(f"### دستیار\n\n{content}\n")

        return "\n".join(lines).rstrip() + "\n"

    def _conversation_title(self) -> str:
        """عنوان گفتگو برای سربرگ فایل خروجی."""
        if self._conversation_id is not None:
            try:
                conversation = self._store.get_conversation(self._conversation_id)
            except sqlite3.Error:
                conversation = None

            if conversation is not None:
                return conversation.title

        first_user = next(
            (
                message["content"]
                for message in self._history
                if message.get("role") == "user" and message.get("content")
            ),
            None,
        )

        return " ".join(str(first_user or "گفتگو").split())[:80]

    def clear_conversation(self) -> None:
        """گفتگوی جاری را پاک می‌کند و صفحه را به حالت اولیه برمی‌گرداند."""
        if self._worker is not None:
            self.shutdown()

        self._clear_transcript()
        self._set_busy(False)
        self.reload_configuration()
        self.conversations_updated.emit()

    def _clear_transcript(self) -> None:
        """پیام‌های نمایش‌داده‌شده و وضعیت گفتگوی جاری را پاک می‌کند."""
        self._generation += 1
        self._flush_timer.stop()
        self._conversation_id = None
        self._history.clear()
        self._pending_text = ""
        self._response_text = ""
        self._stream_failed = False
        self._stop_requested = False
        self._streaming_bubble = None

        for row in self._message_rows:
            self.message_layout.removeWidget(row)
            row.setParent(None)
            row.deleteLater()
        self._message_rows.clear()

        self._refresh_empty_state()

    # ---------------------------------------------------------------------- نمایش

    def _add_bubble(self, role: str, text: str = "") -> MessageBubble:
        """یک حباب پیام را در ترتیب نمایش اضافه می‌کند."""
        bubble = MessageBubble(role, text)

        row = QWidget()
        row.setObjectName("messageRow")

        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(0)

        if role == "user":
            row_layout.addStretch(1)
            row_layout.addWidget(bubble)
        else:
            row_layout.addWidget(bubble)
            row_layout.addStretch(1)

        self.message_layout.insertWidget(self.message_layout.count() - 1, row)
        self._message_rows.append(row)
        self._refresh_empty_state()
        self._scroll_to_bottom()

        return bubble

    def _refresh_empty_state(self) -> None:
        """راهنمای شروع گفتگو فقط زمانی نمایش داده می‌شود که پیامی وجود نداشته باشد."""
        self.empty_state_label.setVisible(not self._message_rows)

    def _scroll_to_bottom(self) -> None:
        """پس از به‌روزرسانی چیدمان، ناحیه پیام‌ها را به انتها می‌برد."""
        QTimer.singleShot(0, self._scroll_to_bottom_now)

    def _scroll_to_bottom_now(self) -> None:
        # ممکن است صفحه در همین لحظه آزاد شده باشد؛ در آن صورت کاری انجام نمیدهیم.
        if shiboken2.isValid(self):
            bar = self.scroll_area.verticalScrollBar()
            bar.setValue(bar.maximum())

    def _set_busy(self, busy: bool) -> None:
        """وضعیت دکمه اصلی را بر اساس اجرا یا پایان درخواست تغییر می‌دهد."""
        self._is_busy = busy
        self.send_button.setText("توقف" if busy else "ارسال")
        self.send_button.setToolTip(
            "توقف پاسخ در حال دریافت" if busy else "ارسال پیام (Enter)"
        )

    def _set_status(self, text: str) -> None:
        """متن راهنمای زیر گفتگو را جایگزین می‌کند."""
        self.status_label.setText(text)


def _repolish(widget: QWidget) -> None:
    """پس از تغییر objectName، استایل جدید را روی ویجت اعمال می‌کند."""
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()
