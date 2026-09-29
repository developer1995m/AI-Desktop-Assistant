"""تست‌های صفحه PDF Assistant."""

import gc

import app.services.pdf_service as pdf_service
from app.services.chat_service import ChatService
from app.services.settings import AppSettings
from app.services.storage import ConversationStore
from app.services.ui_state import UiStateStore
from app.services.voice_service import VoiceService
from app.ui import main_window as main_window_module
from app.ui.main_window import MainWindow
from app.ui.pages.pdf_page import ALREADY_OPEN_STATUS, NO_DOCUMENT_STATUS, PdfPage
from app.ui.widgets.chat_bubble import MessageBubble
from PySide6.QtWidgets import QPushButton

from tests.test_chat_service import FakeClient, make_chunk, write_env
from tests.test_pdf_service import make_pdf


def make_service(tmp_path, monkeypatch, api_key="test-key"):
    """سرویس گفتگو با تنظیمات موقت می‌سازد."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    env_path = write_env(tmp_path, f"OPENAI_API_KEY={api_key}\nOPENAI_MODEL=test-model\n")
    return ChatService(AppSettings(env_path))


def make_page(qt_app, tmp_path, monkeypatch, api_key="test-key"):
    """صفحه PDF با سرویس موقت می‌سازد."""
    return PdfPage(make_service(tmp_path, monkeypatch, api_key=api_key))


def bubble_texts(page) -> list[str]:
    """متن همه حباب‌های نمایش‌داده‌شده در صفحه."""
    return [bubble.text() for bubble in page.findChildren(MessageBubble)]


def error_bubbles(page) -> list[MessageBubble]:
    """حباب‌های خطای صفحه."""
    return [
        bubble for bubble in page.findChildren(MessageBubble) if bubble.objectName() == "errorBubble"
    ]


# ------------------------------------------------------------------- بازکردن سند


def test_page_loads_document_and_shows_preview(qt_app, tmp_path, monkeypatch):
    page = make_page(qt_app, tmp_path, monkeypatch)
    path = make_pdf(tmp_path / "handbook.pdf", ["First page body"])

    try:
        assert page.load_document(str(path)) is True

        assert page.document is not None
        assert page.document.name == "handbook.pdf"
        assert "handbook.pdf" in page.document_label.text()
        assert page.preview_frame.isVisibleTo(page) is True
        assert "First page body" in page.preview_text.toPlainText()
        assert "باز شد" in bubble_texts(page)[0]
        assert page.status_label.text().startswith("آماده است")
    finally:
        page.deleteLater()


def test_page_reports_unreadable_file(qt_app, tmp_path, monkeypatch):
    page = make_page(qt_app, tmp_path, monkeypatch)
    broken = tmp_path / "broken.pdf"
    broken.write_text("not a pdf at all", encoding="utf-8")

    try:
        assert page.load_document(str(broken)) is False

        assert page.document is None
        assert len(error_bubbles(page)) == 1
        assert page.status_label.text() == "خواندن فایل PDF ناموفق بود."
    finally:
        page.deleteLater()


def test_page_without_document_ignores_questions(qt_app, tmp_path, monkeypatch, wait_for):
    page = make_page(qt_app, tmp_path, monkeypatch)
    client = FakeClient([make_chunk("پاسخ")])
    monkeypatch.setattr(ChatService, "_create_client", lambda self: client)

    try:
        page.chat_input.setPlainText("این سند درباره چیست؟")
        page.send_button.click()

        assert page.is_busy is False
        assert bubble_texts(page) == []
        assert page.status_label.text() == NO_DOCUMENT_STATUS
        assert client.calls == []
    finally:
        page.deleteLater()


# ------------------------------------------------------------------- پرسش و پاسخ


def test_page_asks_question_about_document(qt_app, tmp_path, monkeypatch, wait_for):
    page = make_page(qt_app, tmp_path, monkeypatch)
    path = make_pdf(tmp_path / "laws.pdf", ["Unique marker 42"])
    client = FakeClient([make_chunk("پاسخ "), make_chunk("درباره سند")])
    monkeypatch.setattr(ChatService, "_create_client", lambda self: client)

    try:
        assert page.load_document(str(path)) is True

        page.chat_input.setPlainText("مارکر چیست؟")
        page.send_button.click()
        assert page.send_button.text() == "توقف"

        assert wait_for(lambda: not page.is_busy)

        texts = bubble_texts(page)
        assert texts[-2:] == ["مارکر چیست؟", "پاسخ درباره سند"]
        assert page.question_count == 1

        system_content = client.calls[0]["messages"][0]["content"]
        assert "Unique marker 42" in system_content
        assert "laws.pdf" in system_content
        assert client.calls[0]["messages"][-1] == {"role": "user", "content": "مارکر چیست؟"}
    finally:
        page.deleteLater()


def test_page_sends_only_relevant_excerpt_for_long_document(
    qt_app, tmp_path, monkeypatch, wait_for
):
    """در سندهای بلند فقط بخش‌های مرتبط با پرسش به مدل می‌رود (رگرسیون)."""
    monkeypatch.setattr(pdf_service, "CHUNK_CHARS", 60)
    monkeypatch.setattr(pdf_service, "CHUNK_OVERLAP", 0)
    monkeypatch.setattr(pdf_service, "MAX_CONTEXT_CHARS", 150)

    page = make_page(qt_app, tmp_path, monkeypatch)
    path = make_pdf(
        tmp_path / "long.pdf",
        [
            "Alpha topic about invoices and contracts",
            "Beta topic about travel policy",
            "UniqueGamma topic about safety rules",
            "Beta topic about software licenses",
            "Alpha topic about office supplies",
            "Beta topic about payroll rules",
        ],
    )
    client = FakeClient([make_chunk("پاسخ کوتاه")])
    monkeypatch.setattr(ChatService, "_create_client", lambda self: client)

    try:
        assert page.load_document(str(path)) is True

        page.chat_input.setPlainText("قوانین UniqueGamma چیست؟")
        page.send_button.click()
        assert "بخش‌های مرتبط" in page.status_label.text()

        assert wait_for(lambda: not page.is_busy)

        system_content = client.calls[0]["messages"][0]["content"]
        assert "UniqueGamma" in system_content
        assert "Alpha topic" not in system_content
        assert "BEGIN EXCERPTS" in system_content
    finally:
        page.deleteLater()


def test_page_reports_missing_api_key(qt_app, tmp_path, monkeypatch, wait_for):
    page = make_page(qt_app, tmp_path, monkeypatch, api_key="")
    path = make_pdf(tmp_path / "doc.pdf", ["Some text"])

    try:
        assert page.load_document(str(path)) is True
        assert page.status_label.text().startswith("کلید API")

        page.chat_input.setPlainText("سلام")
        page.send_button.click()

        assert wait_for(lambda: not page.is_busy)
        assert "OPENAI_API_KEY" in bubble_texts(page)[-1]
        # سؤال ناموفق در تاریخچه نمی‌ماند تا پرسیدن دوباره تمیز باشد.
        assert page.question_count == 0
    finally:
        page.deleteLater()


def test_page_records_microphone_and_adds_transcription_to_question(
    qt_app, tmp_path, monkeypatch, wait_for
):
    page = make_page(qt_app, tmp_path, monkeypatch)
    path = make_pdf(tmp_path / "doc.pdf", ["Some text"])
    audio_path = tmp_path / "recording.wav"
    audio_path.write_bytes(b"recorded audio")

    try:
        assert page.load_document(str(path)) is True

        class FakeRecorder:
            is_recording = False

            def start_recording(self):
                self.is_recording = True

            def stop_recording(self):
                self.is_recording = False
                return audio_path

            def cancel(self):
                self.is_recording = False

        page._voice_recorder = FakeRecorder()
        monkeypatch.setattr(
            VoiceService, "transcribe_file", lambda self, file_path: "متن تشخیص داده‌شده"
        )

        page.voice_button.click()
        assert page._voice_recorder.is_recording is True
        assert "در حال ضبط" in page.status_label.text()

        page.voice_button.click()
        assert wait_for(lambda: page._voice_worker is None)

        assert page.chat_input.toPlainText() == "متن تشخیص داده‌شده"
        assert "صدا" in page.status_label.text()
        assert not audio_path.exists()
    finally:
        page.deleteLater()


def test_page_stop_cancels_streaming_answer(qt_app, tmp_path, monkeypatch, wait_for):
    page = make_page(qt_app, tmp_path, monkeypatch)
    path = make_pdf(tmp_path / "long.pdf", ["Some text"])
    chunks = [make_chunk(f"chunk-{index} ") for index in range(40)]
    client = FakeClient(chunks, delay=0.02)
    monkeypatch.setattr(ChatService, "_create_client", lambda self: client)

    try:
        assert page.load_document(str(path)) is True

        page.chat_input.setPlainText("خلاصه کن")
        page.send_button.click()
        assert page.send_button.text() == "توقف"

        page.send_button.click()
        assert wait_for(lambda: not page.is_busy)

        assert page.send_button.text() == "ارسال"
        assert len(bubble_texts(page)) == 3
        assert page.status_label.text() == "پاسخ متوقف شد." or page.status_label.text().startswith(
            "آماده است"
        )
    finally:
        page.deleteLater()


# ------------------------------------------------------------------- چند سند


def document_tabs(page) -> list[QPushButton]:
    """برگه‌های سندهای باز در نوار پیش‌نمایش.

    برگه‌های حذف‌شده تا پاک‌شدن رویدادها در حافظه می‌مانند؛ فقط برگه‌های زنده فیلتر می‌شوند.
    """
    return [
        button
        for button in page.findChildren(QPushButton)
        if button.objectName() == "documentTab" and button.isVisibleTo(page)
    ]


def tab_labels(page) -> list[str]:
    """نام سندهای نمایش‌داده‌شده روی برگه‌ها."""
    return [tab.text() for tab in document_tabs(page)]


def test_page_keeps_several_documents_and_asks_across_them(
    qt_app, tmp_path, monkeypatch, wait_for
):
    page = make_page(qt_app, tmp_path, monkeypatch)
    first = make_pdf(tmp_path / "one.pdf", ["First document marker"])
    second = make_pdf(tmp_path / "two.pdf", ["Second document marker"])
    client = FakeClient([make_chunk("پاسخ")])
    monkeypatch.setattr(ChatService, "_create_client", lambda self: client)

    try:
        assert page.load_document(str(first)) is True
        assert page.load_document(str(second)) is True

        assert [document.name for document in page.documents] == ["one.pdf", "two.pdf"]
        assert page.document.name == "two.pdf"
        assert page.close_all_button.isVisibleTo(page) is True
        assert len(document_tabs(page)) == 2
        assert "2 سند باز" in page.document_label.text()
        assert "one.pdf" in page.document_label.text()
        assert "Second document marker" in page.preview_text.toPlainText()

        page.chat_input.setPlainText("تفاوت این دو سند چیست؟")
        page.send_button.click()
        assert wait_for(lambda: not page.is_busy)

        system_content = client.calls[0]["messages"][0]["content"]
        assert "BEGIN DOCUMENT 1: one.pdf" in system_content
        assert "BEGIN DOCUMENT 2: two.pdf" in system_content
        assert "First document marker" in system_content
        assert "Second document marker" in system_content
    finally:
        page.deleteLater()


def test_loading_the_same_file_again_activates_it(qt_app, tmp_path, monkeypatch):
    page = make_page(qt_app, tmp_path, monkeypatch)
    first = make_pdf(tmp_path / "one.pdf", ["Body one"])
    second = make_pdf(tmp_path / "two.pdf", ["Body two"])

    try:
        assert page.load_document(str(first)) is True
        assert page.load_document(str(second)) is True
        assert page.load_document(str(first)) is True

        assert len(page.documents) == 2
        assert page.document.name == "one.pdf"
        assert page.status_label.text() == ALREADY_OPEN_STATUS
        # بار دوم فایل دوباره خوانده نمی‌شود، پس اعلان تازه‌ای هم ساخته نمی‌شود.
        assert sum(1 for text in bubble_texts(page) if "باز شد" in text) == 2
    finally:
        page.deleteLater()


def test_closing_documents_switches_active_and_ends_empty(qt_app, tmp_path, monkeypatch):
    page = make_page(qt_app, tmp_path, monkeypatch)
    first = make_pdf(tmp_path / "a.pdf", ["Body a"])
    second = make_pdf(tmp_path / "b.pdf", ["Body b"])
    third = make_pdf(tmp_path / "c.pdf", ["Body c"])

    try:
        for path in (first, second, third):
            assert page.load_document(str(path)) is True
        assert page.document.name == "c.pdf"

        # بستن سندی که قبل از سند فعال است: سند فعال همان می‌ماند.
        assert page.close_document("b.pdf") is True
        assert [document.name for document in page.documents] == ["a.pdf", "c.pdf"]
        assert page.document.name == "c.pdf"

        # بستن سندی که بعد از سند فعال است هم سند فعال را عوض نمی‌کند.
        assert page.activate_document(str(first)) is True
        assert page.close_document(1) is True
        assert [document.name for document in page.documents] == ["a.pdf"]
        assert page.document.name == "a.pdf"
        # با یک سند، نوار برگه‌ها می‌ماند ولی دکمه «بستن همه» پنهان می‌شود.
        assert len(document_tabs(page)) == 1
        assert page.document_row.isVisibleTo(page) is True
        assert page.close_all_button.isVisibleTo(page) is False

        assert page.close_document(str(first)) is True
        assert page.documents == []
        assert page.document is None
        assert page.preview_frame.isVisibleTo(page) is False
        assert page.status_label.text() == NO_DOCUMENT_STATUS
    finally:
        page.deleteLater()


def test_document_tabs_switch_and_close_documents(qt_app, tmp_path, monkeypatch):
    page = make_page(qt_app, tmp_path, monkeypatch)
    first = make_pdf(tmp_path / "one.pdf", ["Body one"])
    second = make_pdf(tmp_path / "two.pdf", ["Body two"])

    try:
        assert page.load_document(str(first)) is True
        assert page.load_document(str(second)) is True
        assert [tab.property("active") for tab in document_tabs(page)] == [False, True]

        document_tabs(page)[0].click()
        assert page.document.name == "one.pdf"
        assert [tab.property("active") for tab in document_tabs(page)] == [True, False]

        close_buttons = [
            button
            for button in page.findChildren(QPushButton)
            if button.objectName() == "documentTabClose"
        ]
        assert len(close_buttons) == 2
        close_buttons[0].click()

        assert [document.name for document in page.documents] == ["two.pdf"]
        assert page.document.name == "two.pdf"
        assert tab_labels(page) == ["two.pdf"]
        assert len(
            [
                button
                for button in page.findChildren(QPushButton)
                if button.objectName() == "documentTabClose"
                and button.isVisibleTo(page)
            ]
        ) == 1
    finally:
        page.deleteLater()


def test_unknown_document_targets_are_rejected(qt_app, tmp_path, monkeypatch):
    page = make_page(qt_app, tmp_path, monkeypatch)
    path = make_pdf(tmp_path / "only.pdf", ["Body"])

    try:
        assert page.load_document(str(path)) is True

        assert page.close_document("missing.pdf") is False
        assert page.close_document(7) is False
        assert page.activate_document(tmp_path / "nothing.pdf") is False
        assert page.close_document(True) is False
        assert [document.name for document in page.documents] == ["only.pdf"]
    finally:
        page.deleteLater()


# ---------------------------------------------------------------------- پاک‌کردن


def test_clear_keeps_document_but_drops_conversation(qt_app, tmp_path, monkeypatch):
    page = make_page(qt_app, tmp_path, monkeypatch)
    path = make_pdf(tmp_path / "kept.pdf", ["Body text"])

    try:
        assert page.load_document(str(path)) is True
        second = make_pdf(tmp_path / "second.pdf", ["Another body"])
        assert page.load_document(str(second)) is True

        page.clear_conversation()

        assert page.document is not None
        assert page.preview_frame.isVisibleTo(page) is True
        assert bubble_texts(page) == []
        assert page.empty_state_label.isVisibleTo(page) is True
        assert page.question_count == 0
        assert page.status_label.text().startswith("آماده است")
    finally:
        page.deleteLater()


def test_destroyed_page_after_request_keeps_event_loop_alive(
    qt_app, tmp_path, monkeypatch, wait_for
):
    """آزادسازی صفحه پس از یک درخواست نباید به کرش سطح پایین Qt منجر شود (رگرسیون)."""
    page = make_page(qt_app, tmp_path, monkeypatch)
    path = make_pdf(tmp_path / "doc.pdf", ["Body text"])
    monkeypatch.setattr(ChatService, "_create_client", lambda self: FakeClient([make_chunk("باشه")]))

    assert page.load_document(str(path)) is True

    page.chat_input.setPlainText("سلام")
    page.send_button.click()
    assert wait_for(lambda: not page.is_busy)

    del page
    gc.collect()

    for _ in range(25):
        qt_app.processEvents()


# ------------------------------------------------------------- اتصال به پنجره اصلی


def test_main_window_hosts_the_pdf_page(qt_app, tmp_path, monkeypatch, wait_for):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    env_path = write_env(tmp_path, "OPENAI_API_KEY=key\nOPENAI_MODEL=test-model\n")
    monkeypatch.setattr(
        main_window_module, "AppSettings", lambda *args, **kwargs: AppSettings(env_path)
    )

    window = MainWindow(
        chat_store=ConversationStore(tmp_path / "window.db"),
        ui_state=UiStateStore(tmp_path / "ui_state.json"),
    )
    try:
        window.show_page("pdf")
        assert window.page_stack.currentWidget() is window.pdf_page
        # سرویس صفحه PDF همان سرویس پنجره اصلی است تا تنظیمات و کلید تازه بمانند.
        assert window.pdf_page._service is window.chat_service

        path = make_pdf(tmp_path / "window.pdf", ["Window document"])
        assert window.pdf_page.load_document(str(path)) is True

        window.close()
        for _ in range(10):
            qt_app.processEvents()
    finally:
        window.deleteLater()
