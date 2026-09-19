"""تست اتصال صفحات و فهرست گفتگوها به پنجره اصلی."""

import gc

from PySide6.QtWidgets import QMessageBox

from app.services.chat_service import ChatService
from app.services.settings import AppSettings
from app.services.storage import ConversationStore
from app.services.ui_state import UiStateStore
from app.ui import main_window as main_window_module
from app.ui.main_window import MainWindow
from app.ui.widgets.chat_bubble import MessageBubble

from tests.test_chat_service import FakeClient, make_chunk, write_env


def make_window(qt_app, tmp_path, monkeypatch, store=None, ui_state=None):
    """پنجره اصلی با تنظیمات و پایگاه‌داده موقت می‌سازد."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)

    env_path = write_env(tmp_path, "OPENAI_API_KEY=key\nOPENAI_MODEL=test-model\n")
    monkeypatch.setattr(
        main_window_module, "AppSettings", lambda *args, **kwargs: AppSettings(env_path)
    )

    return MainWindow(
        chat_store=store if store is not None else ConversationStore(tmp_path / "chat.db"),
        # وضعیت پنجره در پوشه موقت نوشته می‌شود تا تست، پروژه را آلوده نکند.
        ui_state=ui_state if ui_state is not None else UiStateStore(tmp_path / "ui_state.json"),
    )


def bubble_texts(page) -> list[str]:
    return [bubble.text() for bubble in page.findChildren(MessageBubble)]


def test_main_window_wires_chat_page(qt_app, monkeypatch, tmp_path):
    window = make_window(qt_app, tmp_path, monkeypatch)
    window.show()

    assert window.page_stack.count() == len(window.page_indexes)
    assert "chat" in window.page_indexes

    window.show_page("chat")
    assert window.page_stack.currentWidget() is window.chat_page
    assert window.chat_page.model_label.text() == "مدل: test-model"
    assert window.sidebar.conversations.isVisible() is True

    window.show_page("notes")
    assert window.page_stack.currentWidget() is not window.chat_page
    assert window.sidebar.conversations.isVisible() is False

    # بستن پنجره باید بدون کرش و بدون رشته در حال اجرا انجام شود.
    window.close()
    del window
    gc.collect()

    for _ in range(25):
        qt_app.processEvents()


def test_saved_conversations_are_listed_and_switchable(qt_app, tmp_path, monkeypatch):
    store = ConversationStore(tmp_path / "chat.db")
    first = store.create_conversation("گفتگوی اول")
    store.add_exchange(first, "اول", "پاسخ اول")
    second = store.create_conversation("گفتگوی دوم")
    store.add_exchange(second, "دوم", "پاسخ دوم")

    window = make_window(qt_app, tmp_path, monkeypatch, store=store)
    window.show()

    assert window.chat_page.current_conversation_id == second
    assert sorted(window.sidebar.conversations.buttons) == [first, second]
    assert window.sidebar.conversations.buttons[second].isChecked() is True

    window.sidebar.conversations.buttons[first].click()

    assert window.page_stack.currentWidget() is window.chat_page
    assert window.chat_page.current_conversation_id == first
    assert bubble_texts(window.chat_page) == ["اول", "پاسخ اول"]
    assert window.sidebar.conversations.buttons[first].isChecked() is True
    assert window.sidebar.conversations.buttons[second].isChecked() is False

    window.close()


def test_new_message_adds_conversation_to_the_sidebar(qt_app, tmp_path, monkeypatch, wait_for):
    window = make_window(qt_app, tmp_path, monkeypatch)
    window.show()
    monkeypatch.setattr(
        ChatService, "_create_client", lambda self: FakeClient([make_chunk("باشه")])
    )

    assert window.sidebar.conversations.buttons == {}

    window.chat_page.chat_input.setPlainText("سلام")
    window.chat_page.send_button.click()
    assert wait_for(lambda: not window.chat_page.is_busy)

    conversation_id = window.chat_page.current_conversation_id
    assert conversation_id is not None
    assert list(window.sidebar.conversations.buttons) == [conversation_id]
    assert window.sidebar.conversations.buttons[conversation_id].text() == "سلام"

    window.close()


def test_memory_page_feeds_the_chat_prompt(qt_app, tmp_path, monkeypatch):
    window = make_window(qt_app, tmp_path, monkeypatch)
    window.show()

    window.show_page("chat")
    assert window.chat_page.memory_label.isVisibleTo(window.chat_page) is False

    window.show_page("memory")
    assert window.page_stack.currentWidget() is window.memory_page

    window.memory_page.content_input.setText("نام من مسعود است")
    window.memory_page.add_button.click()

    assert window.chat_store.count_memories() == 1
    assert window.chat_service.active_memories() == ["نام من مسعود است"]
    assert window.chat_page.memory_label.text() == "حافظه فعال: 1"
    assert window.chat_page.memory_label.isVisibleTo(window.chat_page) is True

    # غیرفعال‌کردن حافظه باید بلافاصله در نوار وضعیت صفحه چت دیده شود.
    memory_id = window.chat_store.list_memories()[0].id
    window.memory_page._toggle_memory(memory_id, False)

    assert window.chat_service.active_memories() == []
    assert window.chat_page.memory_label.isVisibleTo(window.chat_page) is False

    window.close()


def test_delete_conversation_requires_confirmation(qt_app, tmp_path, monkeypatch):
    store = ConversationStore(tmp_path / "chat.db")
    conversation_id = store.create_conversation("حذف‌شدنی")
    store.add_exchange(conversation_id, "الف", "ب")

    window = make_window(qt_app, tmp_path, monkeypatch, store=store)
    window.show()

    monkeypatch.setattr(
        QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.No
    )
    window.sidebar.conversations.delete_buttons[conversation_id].click()

    assert store.latest_conversation() is not None
    assert list(window.sidebar.conversations.buttons) == [conversation_id]

    monkeypatch.setattr(
        QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Yes
    )
    window.sidebar.conversations.delete_buttons[conversation_id].click()

    assert store.latest_conversation() is None
    window.close()


def test_setup_banner_leads_to_the_settings_page(qt_app, tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)

    # بدون کلید API: بنر راه‌اندازی اولیه باید کاربر را مستقیم به تنظیمات ببرد.
    env_path = write_env(tmp_path, "")
    monkeypatch.setattr(
        main_window_module, "AppSettings", lambda *args, **kwargs: AppSettings(env_path)
    )
    window = MainWindow(
        chat_store=ConversationStore(tmp_path / "chat.db"),
        ui_state=UiStateStore(tmp_path / "ui_state.json"),
    )
    window.show()

    assert window.chat_page.setup_banner.isVisibleTo(window.chat_page) is True

    window.chat_page.setup_button.click()

    assert window.page_stack.currentWidget() is window.settings_page
    window.close()
    assert window.sidebar.conversations.buttons == {}
    assert window.chat_page.current_conversation_id is None
    assert bubble_texts(window.chat_page) == []

    window.close()
