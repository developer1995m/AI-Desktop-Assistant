"""تست‌های صفحه گفتگو و ویجت‌های آن."""

import gc

import pytest
from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtGui import QGuiApplication, QKeyEvent

from app.services.chat_service import MAX_HISTORY_MESSAGES, ChatService
from app.services.settings import AppSettings
from app.services.storage import ConversationStore
from app.ui.pages.chat_page import ChatPage
from app.ui.widgets.chat_bubble import MessageBubble
from app.ui.widgets.chat_input import ChatInput

from tests.test_chat_service import FakeClient, make_chunk, write_env
from tests.test_error_messages import make_error


def make_service(tmp_path, monkeypatch, api_key="test-key"):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    env_path = write_env(tmp_path, f"OPENAI_API_KEY={api_key}\nOPENAI_MODEL=test-model\n")
    return ChatService(AppSettings(env_path))


def make_page(qt_app, tmp_path, monkeypatch, **kwargs):
    """صفحه گفتگو با سرویس و پایگاه‌داده موقت می‌سازد."""
    service = make_service(tmp_path, monkeypatch, **kwargs)
    store = ConversationStore(tmp_path / "chat.db")
    return ChatPage(service, store)


def bubble_texts(page) -> list[str]:
    """متن همه حباب‌های نمایش‌داده‌شده در صفحه."""
    return [
        bubble.text()
        for bubble in page.findChildren(MessageBubble)
    ]


def test_chat_input_sends_on_enter_and_keeps_shift_enter(qt_app):
    widget = ChatInput()
    calls = []
    widget.send_requested.connect(lambda: calls.append("sent"))

    widget.keyPressEvent(
        QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Return, Qt.KeyboardModifier.NoModifier, "\r")
    )
    assert calls == ["sent"]

    widget.keyPressEvent(
        QKeyEvent(
            QEvent.Type.KeyPress,
            Qt.Key.Key_Return,
            Qt.KeyboardModifier.ShiftModifier,
            "\r",
        )
    )
    assert calls == ["sent"]
    assert widget.toPlainText() == "\n"


def test_take_text_strips_and_clears(qt_app):
    widget = ChatInput()
    widget.setPlainText("  سلام  ")

    assert widget.take_text() == "سلام"
    assert widget.toPlainText() == ""


def test_page_streams_reply_into_bubble(qt_app, tmp_path, monkeypatch, wait_for):
    page = make_page(qt_app, tmp_path, monkeypatch)
    client = FakeClient([make_chunk("سلام"), make_chunk(" کاربر")])
    monkeypatch.setattr(ChatService, "_create_client", lambda self: client)

    page.chat_input.setPlainText("درود")
    page.send_button.click()

    assert wait_for(lambda: not page.is_busy)
    assert bubble_texts(page) == ["درود", "سلام کاربر"]
    assert page._history == [
        {"role": "user", "content": "درود"},
        {"role": "assistant", "content": "سلام کاربر"},
    ]
    assert page.chat_input.toPlainText() == ""


def test_page_reports_missing_api_key(qt_app, tmp_path, monkeypatch, wait_for):
    page = make_page(qt_app, tmp_path, monkeypatch, api_key="")

    page.chat_input.setPlainText("سلام")
    page.send_button.click()

    assert wait_for(lambda: not page.is_busy)
    texts = bubble_texts(page)
    assert texts[0] == "سلام"
    assert "OPENAI_API_KEY" in texts[1]
    # پیام ناموفق در تاریخچه نگه داشته نمی‌شود تا ارسال دوباره تمیز باشد.
    assert page._history == []


def test_page_shows_error_bubble_for_api_failure(qt_app, tmp_path, monkeypatch, wait_for):
    page = make_page(qt_app, tmp_path, monkeypatch)
    client = FakeClient(error=RuntimeError("boom"))
    monkeypatch.setattr(ChatService, "_create_client", lambda self: client)

    page.chat_input.setPlainText("سلام")
    page.send_button.click()

    assert wait_for(lambda: not page.is_busy)
    texts = bubble_texts(page)
    assert "خطای پیش‌بینی‌نشده در ارتباط با مدل: RuntimeError" in texts[1]
    error_bubbles = [
        bubble for bubble in page.findChildren(MessageBubble) if bubble.objectName() == "errorBubble"
    ]
    assert len(error_bubbles) == 1


def test_stop_button_cancels_running_request(qt_app, tmp_path, monkeypatch, wait_for):
    page = make_page(qt_app, tmp_path, monkeypatch)
    full_answer = "".join(f"chunk-{index} " for index in range(40))
    client = FakeClient(
        [make_chunk(f"chunk-{index} ") for index in range(40)],
        delay=0.02,
    )
    monkeypatch.setattr(ChatService, "_create_client", lambda self: client)

    page.chat_input.setPlainText("سلام")
    page.send_button.click()
    assert page.send_button.text() == "توقف"

    page.send_button.click()
    assert wait_for(lambda: not page.is_busy)

    assert page.send_button.text() == "ارسال"
    assert len(bubble_texts(page)) == 2
    # پاسخ نیمه‌کاره همان مقدار دریافت‌شده است و کامل نشده است.
    assert full_answer.startswith(page._response_text)
    assert len(page._response_text) < len(full_answer)
    # وضعیت نهایی باید توقف را گزارش کند، نه آماده‌بودن یا خطا.
    assert page.status_label.text() == "پاسخ متوقف شد."


def test_empty_state_hidden_after_first_message(qt_app, tmp_path, monkeypatch, wait_for):
    page = make_page(qt_app, tmp_path, monkeypatch)
    monkeypatch.setattr(
        ChatService, "_create_client", lambda self: FakeClient([make_chunk("باشه")])
    )

    page.show()
    assert page.empty_state_label.isVisible() is True

    page.chat_input.setPlainText("سلام")
    page.send_button.click()
    assert wait_for(lambda: not page.is_busy)

    assert page.empty_state_label.isVisible() is False

    page.clear_conversation()
    qt_app.processEvents()

    assert page.empty_state_label.isVisible() is True
    assert page._message_rows == []
    assert bubble_texts(page) == []
    assert page._history == []


def test_reload_configuration_reflects_settings_change(qt_app, tmp_path, monkeypatch):
    env_path = write_env(tmp_path, "OPENAI_API_KEY=\n")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    page = ChatPage(
        ChatService(AppSettings(env_path)), ConversationStore(tmp_path / "chat.db")
    )

    assert "OPENAI_API_KEY" in page.status_label.text()

    env_path.write_text("OPENAI_API_KEY=key\nOPENAI_MODEL=other-model\n", encoding="utf-8")
    page.reload_configuration()

    assert page.model_label.text() == "مدل: other-model"
    assert "OPENAI_API_KEY" not in page.status_label.text()


def test_exchange_is_persisted_and_restored(qt_app, tmp_path, monkeypatch, wait_for):
    page = make_page(qt_app, tmp_path, monkeypatch)
    monkeypatch.setattr(
        ChatService, "_create_client", lambda self: FakeClient([make_chunk("درود بر تو")])
    )

    page.chat_input.setPlainText("  سلام  ")
    page.send_button.click()
    assert wait_for(lambda: not page.is_busy)

    store = page._store
    conversation = store.latest_conversation()
    assert conversation is not None
    assert conversation.title == "سلام"
    assert store.load_messages(conversation.id) == [
        {"role": "user", "content": "سلام"},
        {"role": "assistant", "content": "درود بر تو"},
    ]

    restored = ChatPage(page._service, store)
    assert bubble_texts(restored) == ["سلام", "درود بر تو"]
    assert restored._history == [
        {"role": "user", "content": "سلام"},
        {"role": "assistant", "content": "درود بر تو"},
    ]
    assert restored.empty_state_label.isHidden() is True


def test_new_conversation_is_stored_separately(qt_app, tmp_path, monkeypatch, wait_for):
    page = make_page(qt_app, tmp_path, monkeypatch)
    monkeypatch.setattr(
        ChatService, "_create_client", lambda self: FakeClient([make_chunk("باشه")])
    )

    page.chat_input.setPlainText("اول")
    page.send_button.click()
    assert wait_for(lambda: not page.is_busy)

    store = page._store
    first = store.latest_conversation()
    assert first is not None

    page.clear_conversation()
    page.chat_input.setPlainText("دوم")
    page.send_button.click()
    assert wait_for(lambda: not page.is_busy)

    second = store.latest_conversation()
    assert second is not None
    assert second.id != first.id
    assert second.title == "دوم"
    assert [message["content"] for message in store.load_messages(first.id)] == [
        "اول",
        "باشه",
    ]
    assert [message["content"] for message in store.load_messages(second.id)] == [
        "دوم",
        "باشه",
    ]

    restored = ChatPage(page._service, store)
    assert bubble_texts(restored) == ["دوم", "باشه"]


def test_failed_request_is_not_persisted(qt_app, tmp_path, monkeypatch, wait_for):
    page = make_page(qt_app, tmp_path, monkeypatch, api_key="")

    page.chat_input.setPlainText("سلام")
    page.send_button.click()
    assert wait_for(lambda: not page.is_busy)

    assert page._store.latest_conversation() is None


def test_destroyed_page_keeps_event_loop_alive(qt_app, tmp_path, monkeypatch, wait_for):
    """آزاد‌سازی صفحه پس از یک درخواست نباید به کرش سطح پایین Qt منجر شود (رگرسیون)."""
    page = make_page(qt_app, tmp_path, monkeypatch)
    monkeypatch.setattr(
        ChatService, "_create_client", lambda self: FakeClient([make_chunk("سلام")])
    )

    page.chat_input.setPlainText("درود")
    page.send_button.click()
    assert wait_for(lambda: not page.is_busy)

    del page
    gc.collect()

    for _ in range(25):
        qt_app.processEvents()


def test_destroyed_page_after_failed_request(qt_app, tmp_path, monkeypatch, wait_for):
    """مسیر خطا هم باید بدون کرش آزاد شود."""
    page = make_page(qt_app, tmp_path, monkeypatch, api_key="")

    page.chat_input.setPlainText("درود")
    page.send_button.click()
    assert wait_for(lambda: not page.is_busy)

    del page
    gc.collect()

    for _ in range(25):
        qt_app.processEvents()


def test_page_sends_saved_memories_to_the_model(qt_app, tmp_path, monkeypatch, wait_for):
    """حافظه‌های فعال باید واقعاً به پرامپت برسند (رگرسیون: خواندن در رشته کارگر)."""
    store = ConversationStore(tmp_path / "chat.db")
    store.add_memory("نام من مسعود است")
    disabled_id = store.add_memory("این واقعیت خاموش است")
    store.set_memory_enabled(disabled_id, False)
    service = make_service(tmp_path, monkeypatch)

    page = ChatPage(service, store)
    client = FakeClient([make_chunk("سلام")])
    monkeypatch.setattr(ChatService, "_create_client", lambda self: client)

    assert page.memory_label.isVisibleTo(page)
    assert page.memory_label.text() == "حافظه فعال: 1"

    page.chat_input.setPlainText("اسم من چیه؟")
    page.send_button.click()
    assert wait_for(lambda: not page.is_busy)

    sent_messages = client.calls[0]["messages"]
    system_content = sent_messages[0]["content"]

    assert "- نام من مسعود است" in system_content
    assert "این واقعیت خاموش است" not in system_content
    assert sent_messages[-1] == {"role": "user", "content": "اسم من چیه؟"}


# ------------------------------------------------------ کپی و خروجی گفتگو


def test_assistant_bubble_has_a_copy_button(qt_app):
    bubble = MessageBubble("assistant", "پاسخ مدل")

    assert bubble.copy_button is not None
    assert bubble.copy_button.text() == "کپی"


def test_copy_button_places_the_reply_on_the_clipboard(qt_app):
    bubble = MessageBubble("assistant", "متن پاسخ")

    bubble.copy_button.click()

    assert QGuiApplication.clipboard().text() == "متن پاسخ"
    assert bubble.copy_button.text() == "کپی شد ✓"


def test_user_bubble_has_no_copy_button(qt_app):
    assert MessageBubble("user", "سلام").copy_button is None


def test_markdown_transcript_groups_by_role(qt_app, tmp_path, monkeypatch):
    page = make_page(qt_app, tmp_path, monkeypatch)
    page._history.append({"role": "user", "content": "سلام"})
    page._history.append({"role": "assistant", "content": "درود بر شما"})
    page._history.append({"role": "error", "content": "نباید در خروجی بیاید"})

    markdown = page.markdown_transcript()

    assert "### شما" in markdown
    assert "### دستیار" in markdown
    assert "درود بر شما" in markdown
    assert "نباید در خروجی بیاید" not in markdown
    assert markdown.strip().endswith("درود بر شما")


def test_export_writes_a_markdown_file(qt_app, tmp_path, monkeypatch, wait_for):
    page = make_page(qt_app, tmp_path, monkeypatch)
    page._history.append({"role": "user", "content": "سلام"})
    page._history.append({"role": "assistant", "content": "درود"})

    target = tmp_path / "out" / "گفتگو.md"
    monkeypatch.setattr(
        "app.ui.pages.chat_page.QFileDialog.getSaveFileName",
        lambda *args, **kwargs: (str(target), ""),
    )

    page.export_markdown()

    assert "ذخیره شد" in page.status_label.text()
    assert "### شما" in target.read_text(encoding="utf-8")


def test_export_cancelled_by_the_user_writes_nothing(qt_app, tmp_path, monkeypatch):
    page = make_page(qt_app, tmp_path, monkeypatch)
    page._history.append({"role": "user", "content": "سلام"})

    monkeypatch.setattr(
        "app.ui.pages.chat_page.QFileDialog.getSaveFileName",
        lambda *args, **kwargs: ("", ""),
    )

    page.export_markdown()

    assert list(tmp_path.rglob("*.md")) == []


def test_export_without_a_conversation_shows_a_hint(qt_app, tmp_path, monkeypatch):
    page = make_page(qt_app, tmp_path, monkeypatch)

    page.export_markdown()

    assert "گفتگویی برای خروجی گرفتن نیست" in page.status_label.text()


def test_history_hint_appears_after_the_window_is_passed(qt_app, tmp_path, monkeypatch):
    page = make_page(qt_app, tmp_path, monkeypatch)
    page.show()

    # پنجره تاریخچه بر پایه شمار پیام است، نه شمار نوبت گفتگو.
    for index in range(MAX_HISTORY_MESSAGES + 3):
        page._history.append({"role": "user", "content": f"پیام {index}"})

    page._update_history_hint()

    assert page.history_label.isVisibleTo(page) is True
    assert "3 پیام قدیمی‌تر" in page.history_label.text()


def test_history_hint_is_hidden_inside_the_window(qt_app, tmp_path, monkeypatch):
    page = make_page(qt_app, tmp_path, monkeypatch)
    page.show()

    page._history.append({"role": "user", "content": "سلام"})
    page._history.append({"role": "assistant", "content": "درود"})
    page._update_history_hint()

    assert page.history_label.isVisibleTo(page) is False
    assert page.history_label.text() == ""


def test_history_hint_counts_only_real_conversation_messages(qt_app, tmp_path, monkeypatch):
    """خطاهای نمایش‌داده‌شده پیام گفتگو نیستند و نباید در شمارش بیایند."""
    page = make_page(qt_app, tmp_path, monkeypatch)

    for index in range(MAX_HISTORY_MESSAGES):
        page._history.append({"role": "user", "content": f"پیام {index}"})
    page._update_history_hint()
    assert page.history_label.isVisibleTo(page) is False

    page._history.append({"role": "error", "content": "خطا"})
    page._update_history_hint()
    assert page.history_label.isVisibleTo(page) is False

    page._history.append({"role": "assistant", "content": "پاسخ"})
    page._update_history_hint()
    assert page.history_label.isVisibleTo(page) is True
    assert "1 پیام قدیمی‌تر" in page.history_label.text()


@pytest.mark.parametrize("role", ["user", "assistant", "error"])
def test_bubble_appends_text(qt_app, role):
    bubble = MessageBubble(role, "الف")

    bubble.append_text("ب")

    assert bubble.text() == "الفب"
    assert bubble.objectName() == f"{role}Bubble"


# ------------------------------------------------------------- راه‌اندازی اولیه


def make_page_with_settings(qt_app, tmp_path, monkeypatch, content: str):
    """صفحه گفتگو همراه با شیء تنظیمات می‌سازد تا بتوان کلید را بعداً ذخیره کرد."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)

    settings = AppSettings(write_env(tmp_path, content))
    page = ChatPage(ChatService(settings), ConversationStore(tmp_path / "chat.db"))
    return page, settings


def test_setup_banner_is_visible_until_a_key_is_saved(qt_app, tmp_path, monkeypatch):
    page, settings = make_page_with_settings(qt_app, tmp_path, monkeypatch, "")

    # بدون کلید، کاربر پیش از نوشتن پیام راهنمای راه‌اندازی را می‌بیند.
    assert page.setup_banner.isVisibleTo(page) is True
    assert page.setup_button.text() == "باز کردن تنظیمات"

    settings.save(OPENAI_API_KEY="fresh-key")
    page.reload_configuration()

    assert page.setup_banner.isVisibleTo(page) is False
    assert "آماده است" in page.status_label.text()


def test_setup_banner_returns_when_the_key_is_removed(qt_app, tmp_path, monkeypatch):
    page, settings = make_page_with_settings(
        qt_app, tmp_path, monkeypatch, "OPENAI_API_KEY=key\n"
    )

    assert page.setup_banner.isVisibleTo(page) is False

    settings.save(OPENAI_API_KEY="")
    page.reload_configuration()

    assert page.setup_banner.isVisibleTo(page) is True


def test_setup_banner_does_not_collide_with_the_transcript(qt_app, tmp_path, monkeypatch):
    page, _ = make_page_with_settings(qt_app, tmp_path, monkeypatch, "")
    page.resize(1100, 700)
    page.show()
    qt_app.processEvents()

    banner = page.setup_banner
    button = page.setup_button

    # بنر باید پایین‌تر از سربرگ و بالاتر از ناحیه گفتگو بنشیند.
    assert banner.height() > 40
    assert banner.mapTo(page, QPoint(0, 0)).y() + banner.height() <= page.scroll_area.geometry().top()

    # متن دکمه نباید بریده شود و دکمه نباید از قاب بنر بیرون بزند.
    hint = button.sizeHint()
    assert button.width() >= hint.width()
    assert button.mapTo(banner, QPoint(0, 0)).x() + button.width() <= banner.width()


def test_setup_button_asks_for_the_settings_page(qt_app, tmp_path, monkeypatch):
    page, _ = make_page_with_settings(qt_app, tmp_path, monkeypatch, "")
    requests: list[str] = []
    page.open_settings_requested.connect(lambda: requests.append("settings"))

    page.setup_button.click()

    assert requests == ["settings"]


def test_api_failure_shows_a_friendly_message(qt_app, tmp_path, monkeypatch, wait_for):
    page = make_page(qt_app, tmp_path, monkeypatch)
    monkeypatch.setattr(
        ChatService,
        "_create_client",
        lambda self: FakeClient(
            error=make_error(
                "AuthenticationError",
                status=401,
                message="Invalid API key provided: sk-secret",
            )
        ),
    )

    page.chat_input.setPlainText("سلام")
    page._handle_primary_clicked()

    assert wait_for(lambda: any("کلید API پذیرفته نشد" in text for text in bubble_texts(page)))
    # متن خام و انگلیسی SDK نباید به کاربر نشان داده شود.
    assert not any("sk-secret" in text for text in bubble_texts(page))
