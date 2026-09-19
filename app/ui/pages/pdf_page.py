"""صفحه دستیار PDF؛ باز کردن چند سند و پرسیدن سؤال از محتوای آن‌ها."""

from __future__ import annotations

from pathlib import Path

import shiboken6 as shiboken2

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.services.chat_service import ChatService
from app.services.pdf_service import (
    PdfDocument,
    PdfError,
    documents_system_prompt,
    documents_use_excerpts,
    load_pdf,
)
from app.ui.widgets.chat_bubble import MessageBubble
from app.ui.widgets.chat_input import ChatInput
from app.ui.widgets.document_tabs import DocumentTabs
from app.ui.workers import ChatStreamWorker

EMPTY_STATE_TEXT = (
    "هنوز فایلی باز نشده است.\n"
    "با «افزودن PDF» یک یا چند فایل انتخاب کنید و بعد از محتوای آن‌ها سؤال بپرسید."
)
NO_DOCUMENT_STATUS = "برای پرسیدن سؤال، ابتدا یک یا چند فایل PDF باز کنید."
READY_STATUS = "آماده است — سؤال خود را درباره این سند بنویسید و Enter بزنید."
MULTI_READY_TEMPLATE = "آماده است — {count} سند باز است؛ سؤال خود را درباره همه بپرسید."
SEARCHING_STATUS = "در حال دریافت پاسخ…"
# در سندهای بلند فقط بخش‌های مرتبط سند به مدل می‌رود؛ همین را شفاف اعلام می‌کنیم.
EXCERPT_STATUS = "در حال دریافت پاسخ… (تنها بخش‌های مرتبط سندها فرستاده می‌شود)"
NO_KEY_STATUS = "کلید API تنظیم نشده است؛ مقدار OPENAI_API_KEY را در فایل .env وارد کنید."
ALREADY_OPEN_STATUS = "این سند از قبل باز است؛ همان برگه فعال شد."
PREVIEW_CHARS = 6000
STREAM_PLACEHOLDER = "…"
FLUSH_INTERVAL_MS = 60
NAME_LIMIT = 28


def ready_status(count: int) -> str:
    """متن راهنمای آماده‌بودن بر اساس تعداد سندهای باز."""
    if count <= 1:
        return READY_STATUS

    return MULTI_READY_TEMPLATE.format(count=count)


def _shorten(name: str, limit: int = NAME_LIMIT) -> str:
    """نام فایل بلند را برای نمایش در برگه کوتاه می‌کند."""
    return name if len(name) <= limit else name[: limit - 1] + "…"


class PdfPage(QWidget):
    """دستیار PDF: استخراج متن یک یا چند سند و گفتگو درباره آن‌ها."""

    def __init__(self, service: ChatService, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self.setObjectName("pdfPage")

        self._service = service
        self._documents: list[PdfDocument] = []
        self._active_index = -1
        self._history: list[dict[str, str]] = []
        self._rows: list[QWidget] = []
        self._worker: ChatStreamWorker | None = None
        self._streaming_bubble: MessageBubble | None = None
        self._generation = 0
        self._pending_text = ""
        self._response_text = ""
        self._stream_failed = False
        self._is_busy = False

        self._flush_timer = QTimer(self)
        self._flush_timer.setInterval(FLUSH_INTERVAL_MS)
        self._flush_timer.timeout.connect(self._flush_pending_text)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 24, 32, 24)
        layout.setSpacing(14)
        layout.addWidget(self._create_toolbar())
        layout.addWidget(self._create_body(), 1)
        layout.addWidget(self._create_status())
        layout.addWidget(self._create_composer())

        self.reload_configuration()

    # ------------------------------------------------------------------ ساخت رابط

    def _create_toolbar(self) -> QWidget:
        """نوار بالای صفحه شامل عنوان، مشخصات سندها و دکمه‌های باز کردن و پاک‌کردن."""
        toolbar = QWidget()

        layout = QHBoxLayout(toolbar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        title_label = QLabel("دستیار PDF")
        title_label.setObjectName("pageTitle")

        self.model_label = QLabel()
        self.model_label.setObjectName("modelChip")

        self.document_label = QLabel("فایلی باز نشده")
        self.document_label.setObjectName("documentChip")
        # نام فایل‌های بلند نوار بالا را به‌هم نریزند؛ متن کامل در tooltip می‌ماند.
        self.document_label.setMaximumWidth(360)

        self.open_button = QPushButton("افزودن PDF")
        self.open_button.setObjectName("primaryButton")
        self.open_button.setFixedHeight(34)
        self.open_button.setToolTip("یک یا چند فایل PDF انتخاب کنید")
        self.open_button.clicked.connect(self.open_document_dialog)

        self.close_all_button = QPushButton("بستن همه")
        self.close_all_button.setObjectName("ghostButton")
        self.close_all_button.setToolTip("همه سندهای باز را ببندید")
        self.close_all_button.setVisible(False)
        self.close_all_button.clicked.connect(self.close_all_documents)

        self.clear_button = QPushButton("گفتگوی جدید")
        self.clear_button.setObjectName("ghostButton")
        self.clear_button.clicked.connect(self.clear_conversation)

        layout.addWidget(title_label)
        layout.addWidget(self.model_label)
        layout.addWidget(self.document_label)
        layout.addStretch(1)
        layout.addWidget(self.open_button)
        layout.addWidget(self.close_all_button)
        layout.addWidget(self.clear_button)

        return toolbar

    def _create_body(self) -> QWidget:
        """پیش‌نمایش متن سند در کنار ناحیه گفتگو قرار می‌گیرد."""
        body = QWidget()

        layout = QHBoxLayout(body)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        layout.addWidget(self._create_preview(), 2)
        layout.addWidget(self._create_transcript(), 3)

        return body

    def _create_preview(self) -> QFrame:
        """کادر برگه سندهای باز و پیش‌نمایش متن سند فعال."""
        frame = QFrame()
        frame.setObjectName("pdfPreviewFrame")
        self.preview_frame = frame

        layout = QVBoxLayout(frame)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        heading = QLabel("متن استخراج‌شده")
        heading.setObjectName("panelHeading")
        self.preview_heading = heading

        self.document_row = DocumentTabs()
        self.document_row.document_activated.connect(self.activate_document)
        self.document_row.document_close_requested.connect(self.close_document)
        self.document_row.setVisible(False)

        self.preview_text = QTextEdit()
        self.preview_text.setObjectName("pdfPreview")
        self.preview_text.setReadOnly(True)
        self.preview_text.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)

        layout.addWidget(heading)
        layout.addWidget(self.document_row)
        layout.addWidget(self.preview_text, 1)

        frame.setVisible(False)

        return frame

    def _create_transcript(self) -> QScrollArea:
        """ناحیه اسکرول‌شونده پرسش‌ها و پاسخ‌ها."""
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
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll_area.setWidget(self.transcript_container)

        return self.scroll_area

    def _create_status(self) -> QLabel:
        """نوار وضعیت زیر گفتگو."""
        self.status_label = QLabel()
        self.status_label.setObjectName("chatStatus")
        self.status_label.setWordWrap(True)

        return self.status_label

    def _create_composer(self) -> QWidget:
        """کادر نوشتن سؤال و دکمه ارسال."""
        composer = QWidget()

        layout = QHBoxLayout(composer)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        self.chat_input = ChatInput()
        self.chat_input.send_requested.connect(self._submit_from_input)

        self.send_button = QPushButton("ارسال")
        self.send_button.setObjectName("primaryButton")
        self.send_button.setFixedHeight(44)
        self.send_button.clicked.connect(self._handle_primary_clicked)

        layout.addWidget(self.chat_input, 1)
        layout.addWidget(self.send_button, 0, Qt.AlignmentFlag.AlignBottom)

        return composer

    # --------------------------------------------------------------------- تنظیمات

    def reload_configuration(self) -> None:
        """تنظیمات را دوباره می‌خواند و وضعیت آماده‌بودن را نشان می‌دهد."""
        self._service.reload_configuration()
        self.model_label.setText(f"مدل: {self._service.model}")

        if not self._documents:
            self._set_status(NO_DOCUMENT_STATUS)
            return

        if self._service.is_configured():
            self._set_status(ready_status(len(self._documents)))
        else:
            self._set_status(NO_KEY_STATUS)

    @property
    def is_busy(self) -> bool:
        """آیا درخواستی در حال اجراست؟"""
        return self._is_busy

    @property
    def documents(self) -> list[PdfDocument]:
        """فهرست سندهای باز به ترتیب باز شدن."""
        return list(self._documents)

    @property
    def document(self) -> PdfDocument | None:
        """سند فعال (اولین سند در نبود انتخاب)."""
        if not self._documents:
            return None

        return self._documents[self._active_index]

    @property
    def question_count(self) -> int:
        """تعداد پرسش‌های مطرح‌شده در گفتگوی جاری."""
        return sum(1 for message in self._history if message["role"] == "user")

    # ------------------------------------------------------------------- بازکردن فایل

    def open_document_dialog(self) -> None:
        """از کاربر یک یا چند فایل PDF می‌گیرد و آن‌ها را باز می‌کند."""
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "انتخاب فایل PDF",
            "",
            "PDF (*.pdf)",
        )

        for path in paths:
            self.load_document(path)

    def load_document(self, path: str) -> bool:
        """یک سند را باز می‌کند، پیش‌نمایش را نشان می‌دهد و آن را فعال می‌کند.

        سندهای قبلی باز می‌مانند تا بتوان از همه با هم پرسید. اگر همان فایل از قبل
        باز باشد، فقط همان برگه فعال می‌شود. خروجی `False` یعنی خواندن فایل ناموفق
        بوده و پیام خطا نمایش داده شده است.
        """
        existing = self._document_index(path)
        if existing >= 0:
            self.activate_document(existing)
            self._set_status(ALREADY_OPEN_STATUS)
            return True

        try:
            document = load_pdf(path)
        except PdfError as error:
            self._show_error(str(error))
            return False

        self._documents.append(document)
        self._active_index = len(self._documents) - 1
        self._refresh_documents()
        self.chat_input.setFocus()

        self._add_bubble(
            "assistant",
            f"«{document.name}» باز شد — {document.summary()}\nسؤال خود را بپرسید.",
        )
        self._set_status(
            ready_status(len(self._documents)) if self._service.is_configured() else NO_KEY_STATUS
        )

        return True

    def activate_document(self, target: int | str | Path | PdfDocument) -> bool:
        """سند فعال را عوض می‌کند و پیش‌نمایش آن را نشان می‌دهد."""
        index = self._document_index(target)
        if index < 0:
            return False

        self._active_index = index
        self._refresh_documents()

        return True

    def close_document(self, target: int | str | Path | PdfDocument) -> bool:
        """یک سند باز را می‌بندد و اگر آخرین سند بود به حالت شروع برمی‌گردد."""
        index = self._document_index(target)
        if index < 0:
            return False

        document = self._documents.pop(index)

        if not self._documents:
            self._active_index = -1
            self.preview_frame.setVisible(False)
        elif index < self._active_index or self._active_index >= len(self._documents):
            # سند بسته‌شده قبل از سند فعال بود؛ همان برگه فعال می‌ماند یا به آخری می‌رود.
            self._active_index = min(self._active_index, len(self._documents) - 1)
        elif index == self._active_index:
            self._active_index = min(index, len(self._documents) - 1)

        self._refresh_documents()
        self._add_bubble("assistant", f"«{document.name}» بسته شد.")

        if not self._documents:
            self._set_status(NO_DOCUMENT_STATUS)

        return True

    def close_all_documents(self) -> None:
        """همه سندهای باز را می‌بندد."""
        if not self._documents:
            return

        self._documents.clear()
        self._active_index = -1
        self.preview_text.clear()
        self.preview_frame.setVisible(False)
        self._refresh_documents()
        self._set_status(NO_DOCUMENT_STATUS)

    def clear_conversation(self) -> None:
        """گفتگوی جاری را پاک می‌کند و سندهای باز را نگه می‌دارد."""
        if self._worker is not None:
            self.shutdown()

        self._clear_transcript()
        self._set_busy(False)
        self._set_status(ready_status(len(self._documents)) if self._documents else NO_DOCUMENT_STATUS)

    # ------------------------------------------------------------------ نمایش سندها

    def _document_index(self, target: int | str | Path | PdfDocument) -> int:
        """شماره سند را از ورودی‌های مختلف (اندیس، مسیر، نام یا خود سند) پیدا می‌کند."""
        if isinstance(target, bool):  # bool زیرمجموعه int است؛ اینجا اشتباه رایج است.
            return -1

        if isinstance(target, int):
            if -len(self._documents) <= target < len(self._documents):
                return target % len(self._documents)

            return -1

        if isinstance(target, PdfDocument):
            wanted = target.path
        else:
            wanted = Path(target)

        for index, document in enumerate(self._documents):
            if document.path == wanted or document.name == wanted.name:
                return index

        return -1

    def _refresh_documents(self) -> None:
        """نوار برگه‌ها، پیش‌نمایش و برچسب سندها را با وضعیت جاری هم‌گام می‌کند."""
        self._rebuild_document_row()

        has_documents = bool(self._documents)
        self.preview_frame.setVisible(has_documents)
        self.close_all_button.setVisible(len(self._documents) > 1)
        # با یک سند هم نوار برگه‌ها می‌ماند تا دکمه بستن همان سند در دسترس باشد.
        self.document_row.setVisible(has_documents)

        if not has_documents:
            self.preview_text.clear()
            self.preview_heading.setText("متن استخراج‌شده")
            self.document_label.setText("فایلی باز نشده")
            self.document_label.setToolTip("")
            return

        document = self._documents[self._active_index]
        self.preview_text.setPlainText(document.preview(PREVIEW_CHARS))
        self.preview_heading.setText(f"متن استخراج‌شده — {document.name}")
        self.document_label.setText(self._documents_text())
        self.document_label.setToolTip(self._documents_tooltip())
        self.chat_input.setPlaceholderText(
            "از محتوای این سند چه می‌خواهید بدانید؟"
            if len(self._documents) == 1
            else "از میان این سندها چه می‌خواهید بدانید؟"
        )

    def _documents_text(self) -> str:
        """متن کوتاه نوار بالا برای سندهای باز."""
        if len(self._documents) == 1:
            document = self._documents[0]

            return f"{document.name} — {document.summary()}"

        names = "، ".join(_shorten(document.name, 18) for document in self._documents[:3])
        if len(self._documents) > 3:
            names += f" و {len(self._documents) - 3} سند دیگر"

        return f"{len(self._documents)} سند باز — {names}"

    def _documents_tooltip(self) -> str:
        """متن کامل سندهای باز برای tooltip."""
        lines = [
            f"{index}. {document.name} — {document.summary()}\n{document.path}"
            for index, document in enumerate(self._documents, start=1)
        ]

        return "\n\n".join(lines)

    def _rebuild_document_row(self) -> None:
        """تب‌های سندهای باز را با state فعلی هم‌گام می‌کند."""
        self.document_row.set_documents(self._documents, self._active_index)

    # ---------------------------------------------------------------------- ارسال

    def _submit_from_input(self) -> None:
        """ارسال سؤال با Enter؛ در حین اجرای درخواست نادیده گرفته می‌شود."""
        if self._is_busy:
            return

        self._send(self.chat_input.take_text())

    def _handle_primary_clicked(self) -> None:
        """دکمه اصلی در حالت عادی می‌فرستد و در حین پاسخ، درخواست را متوقف می‌کند."""
        if self._is_busy:
            self._stop_streaming()
            return

        self._send(self.chat_input.take_text())

    def _send(self, text: str) -> None:
        """سؤال کاربر را نمایش می‌دهد و پاسخ مدل را به‌صورت جریانی می‌گیرد."""
        if not text:
            return

        if not self._documents:
            self._set_status(NO_DOCUMENT_STATUS)
            return

        self._add_bubble("user", text)
        self._history.append({"role": "user", "content": text})

        excerpts = documents_use_excerpts(self._documents, text)

        self._streaming_bubble = self._add_bubble("assistant", STREAM_PLACEHOLDER)
        self._pending_text = ""
        self._response_text = ""
        self._stream_failed = False

        self._set_busy(True)
        self._set_status(EXCERPT_STATUS if excerpts else SEARCHING_STATUS)

        generation = self._generation
        worker = ChatStreamWorker(
            self._service,
            list(self._history[:-1]),
            text,
            memories=[],
            system_prompt=documents_system_prompt(self._documents, question=text),
        )
        worker.chunk_received.connect(lambda chunk, gen=generation: self._on_chunk(gen, chunk))
        worker.failed.connect(lambda message, gen=generation: self._on_failed(gen, message))
        worker.finished.connect(lambda gen=generation: self._on_worker_finished(gen))

        self._worker = worker
        worker.start()

    def _stop_streaming(self) -> None:
        """پاسخ در حال دریافت را متوقف می‌کند."""
        worker = self._worker
        if worker is None:
            return

        worker.request_stop()

    def stop_response(self) -> None:
        """اگر پاسخی در حال دریافت باشد، آن را متوقف می‌کند."""
        if self._is_busy:
            self._stop_streaming()
        self._set_status("پاسخ متوقف شد.")

    def shutdown(self) -> None:
        """درخواست در حال اجرا را متوقف می‌کند تا برنامه بدون هشدار بسته شود."""
        worker = self._worker
        if worker is None:
            return

        worker.request_stop()
        worker.wait(2000)
        self._worker = None

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
        """پس از پایان درخواست، وضعیت صفحه و تاریخچه پرسش‌ها را به‌روز می‌کند."""
        if generation != self._generation or self._worker is None:
            return

        self._flush_timer.stop()
        self._flush_pending_text()
        self._streaming_bubble = None

        if self._stream_failed:
            # سؤال ناموفق از تاریخچه حذف می‌شود تا پرسیدن دوباره تمیز باشد.
            self._history.pop()
        elif self._response_text.strip():
            self._history.append({"role": "assistant", "content": self._response_text})
        else:
            self._set_status("پاسخی از مدل دریافت نشد.")

        # مرجع QThread همین‌جا آزاد می‌شود؛ وصل‌کردن آن به والد یا deleteLater باعث کرش Qt می‌شود.
        self._worker = None
        self._set_busy(False)

        if not self._stream_failed and self._service.is_configured() and self._documents:
            self._set_status(ready_status(len(self._documents)))

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
        self._rows.append(row)
        self._refresh_empty_state()
        self._scroll_to_bottom()

        return bubble

    def _show_error(self, message: str) -> None:
        """خطای خواندن فایل را هم در گفتگو و هم در نوار وضعیت نشان می‌دهد."""
        self._add_bubble("error", message)
        self._set_status("خواندن فایل PDF ناموفق بود.")

    def _clear_transcript(self) -> None:
        """پیام‌های نمایش‌داده‌شده و وضعیت گفتگوی جاری را پاک می‌کند."""
        self._generation += 1
        self._flush_timer.stop()
        self._history.clear()
        self._pending_text = ""
        self._response_text = ""
        self._stream_failed = False
        self._streaming_bubble = None

        for row in self._rows:
            self.message_layout.removeWidget(row)
            row.setParent(None)
            row.deleteLater()
        self._rows.clear()

        self._refresh_empty_state()

    def _refresh_empty_state(self) -> None:
        """راهنمای شروع فقط زمانی نمایش داده می‌شود که پیامی وجود نداشته باشد."""
        self.empty_state_label.setVisible(not self._rows)

    def _scroll_to_bottom(self) -> None:
        """پس از به‌روزرسانی چیدمان، ناحیه پیام‌ها را به انتها می‌برد."""
        QTimer.singleShot(0, self._scroll_to_bottom_now)

    def _scroll_to_bottom_now(self) -> None:
        # ممکن است صفحه در همین لحظه آزاد شده باشد؛ در آن صورت کاری انجام نمی‌دهیم.
        if shiboken2.isValid(self):
            bar = self.scroll_area.verticalScrollBar()
            bar.setValue(bar.maximum())

    def _set_busy(self, busy: bool) -> None:
        """وضعیت دکمه اصلی را بر اساس اجرا یا پایان درخواست تغییر می‌دهد."""
        self._is_busy = busy
        self.send_button.setText("توقف" if busy else "ارسال")
        self.send_button.setToolTip(
            "توقف پاسخ در حال دریافت" if busy else "ارسال سؤال درباره سندها"
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
