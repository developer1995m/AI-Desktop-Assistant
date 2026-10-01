"""تست‌های صفحه داشبورد."""

from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QGridLayout, QPushButton

from app.services.chat_service import ChatService
from app.services.storage import ConversationStore
from app.ui.main_window import MainWindow
from app.ui.pages.dashboard_page import DashboardPage, preview_text
from app.ui.theme import DARK, DARK_PALETTE, stylesheet

from tests.test_chat_service import FakeClient, make_chunk
from tests.test_main_window import make_window


def make_dashboard(tmp_path):
    store = ConversationStore(tmp_path / "chat.db")
    return store, DashboardPage(store)


def open_buttons_of(dashboard: DashboardPage) -> list[QPushButton]:
    """دکمه‌های «بازکردن» ردیف‌های گفتگوهای اخیر را برمی‌گرداند."""
    buttons = []

    for row in dashboard._rows:
        buttons.extend(
            button for button in row.findChildren(QPushButton) if button.text() == "بازکردن"
        )

    return buttons


def test_stats_and_last_message(tmp_path):
    store = ConversationStore(tmp_path / "chat.db")
    first = store.create_conversation("اول")
    store.add_exchange(first, "سلام", "درود")
    second = store.create_conversation("دوم")
    store.add_exchange(second, "پرسش دوم", "پاسخ دوم")

    stats = store.stats()
    assert (stats.conversation_count, stats.message_count) == (2, 4)
    assert (stats.user_message_count, stats.assistant_message_count) == (2, 2)

    assert store.last_message(first) == "درود"
    assert store.last_message(999) is None

    empty_store = ConversationStore(tmp_path / "empty.db")
    empty_stats = empty_store.stats()
    assert empty_stats.conversation_count == 0
    assert empty_stats.message_count == 0


def test_preview_text_rules():
    assert preview_text(None) == "—"
    assert preview_text("") == "—"
    assert preview_text("  سلام\nدنیا  ") == "سلام دنیا"

    long_preview = preview_text("خ" * 200, max_length=25)
    assert len(long_preview) == 25
    assert long_preview.endswith("…")


def test_dashboard_shows_empty_state(qt_app, tmp_path):
    store, dashboard = make_dashboard(tmp_path)
    dashboard.show()

    assert dashboard._rows == []
    assert dashboard.empty_label.isVisible() is True
    assert dashboard._container.isVisible() is False
    assert dashboard.chats_card.value_label.text() == "0"

    # گفتگوی بدون هیچ پیامی در فهرست هم می‌آید اما پیش‌نمایش خالی نشان می‌دهد.
    store.create_conversation("فقط عنوان")
    dashboard.refresh()

    assert dashboard.chats_card.value_label.text() == "1"
    assert len(dashboard._rows) == 1
    assert dashboard.empty_label.isHidden() is True
    assert len(open_buttons_of(dashboard)) == 1


def test_dashboard_scroll_background_uses_dark_theme(qt_app, tmp_path):
    store, dashboard = make_dashboard(tmp_path)
    dashboard.resize(900, 700)
    dashboard.setStyleSheet(stylesheet(DARK))
    dashboard.show()
    qt_app.processEvents()

    point = dashboard.scroll_area.viewport().mapTo(dashboard, dashboard.scroll_area.viewport().rect().topLeft())
    image = QImage(dashboard.size(), QImage.Format.Format_ARGB32)
    image.fill(0)
    dashboard.render(image)

    assert image.pixelColor(point) == QColor(DARK_PALETTE["window"])

    dashboard.close()
    store.close()


def test_dashboard_stat_cards_reflow_into_two_columns(qt_app, tmp_path):
    store, dashboard = make_dashboard(tmp_path)
    dashboard.resize(520, 360)
    dashboard.show()
    qt_app.processEvents()

    grid = dashboard.findChild(QGridLayout)
    assert grid is not None
    assert grid.getItemPosition(grid.indexOf(dashboard.chats_card))[:2] == (0, 0)
    assert grid.getItemPosition(grid.indexOf(dashboard.messages_card))[:2] == (0, 1)
    assert grid.getItemPosition(grid.indexOf(dashboard.sent_card))[:2] == (1, 0)
    assert grid.getItemPosition(grid.indexOf(dashboard.replies_card))[:2] == (1, 1)
    assert all(
        label.wordWrap()
        for card in (
            dashboard.chats_card,
            dashboard.messages_card,
            dashboard.sent_card,
            dashboard.replies_card,
        )
        for label in card.findChildren(type(dashboard.empty_label))
        if label.objectName() == "statTitle"
    )
    assert dashboard.scroll_area.widgetResizable()
    assert dashboard.scroll_area.verticalScrollBar().maximum() > 0
    dashboard.scroll_area.verticalScrollBar().setValue(
        dashboard.scroll_area.verticalScrollBar().maximum()
    )
    qt_app.processEvents()
    assert dashboard.recent_frame.isVisible()

    dashboard.close()
    store.close()


def test_dashboard_lists_recent_conversations_with_preview(qt_app, tmp_path):
    store, dashboard = make_dashboard(tmp_path)
    conversation_id = store.create_conversation("گفتگوی اول")
    store.add_exchange(conversation_id, "سوال اول", "جواب اول")

    dashboard.refresh()
    dashboard.show()

    assert dashboard.empty_label.isHidden() is True
    assert len(dashboard._rows) == 1
    assert dashboard.chats_card.value_label.text() == "1"
    assert dashboard.messages_card.value_label.text() == "2"
    assert len(open_buttons_of(dashboard)) == 1

    # گفتگوی تازه‌تر بالای فهرست می‌نشیند.
    newer = store.create_conversation("گفتگوی تازه")
    store.add_exchange(newer, "سوال تازه", "جواب تازه")
    dashboard.refresh()

    assert len(dashboard._rows) == 2
    previews = [
        label.text()
        for row in dashboard._rows
        for label in row.findChildren(type(dashboard.empty_label))
        if label.objectName() == "recentRowPreview"
    ]
    assert previews[0] == "جواب تازه"
    assert previews[1] == "جواب اول"


def test_dashboard_row_click_opens_conversation(qt_app, tmp_path):
    store, dashboard = make_dashboard(tmp_path)
    conversation_id = store.create_conversation("گفتگوی کلیک‌شدنی")
    store.add_exchange(conversation_id, "سلام", "درود بر شما")
    dashboard.refresh()
    dashboard.show()

    opened: list[int] = []
    dashboard.open_conversation_requested.connect(opened.append)

    buttons = open_buttons_of(dashboard)
    assert len(buttons) == 1
    buttons[0].click()

    assert opened == [conversation_id]


def test_main_window_dashboard_is_live(qt_app, tmp_path, monkeypatch, wait_for):
    window = make_window(qt_app, tmp_path, monkeypatch)
    window.show()

    dashboard = window.dashboard_page
    assert dashboard.chats_card.value_label.text() == "0"
    assert dashboard.empty_label.isVisible() is True

    # یک گفتگو از طریق صفحه چت ساخته می‌شود.
    monkeypatch.setattr(
        ChatService, "_create_client", lambda self: FakeClient([make_chunk("پاسخ")])
    )
    window.show_page("chat")
    window.chat_page.chat_input.setPlainText("سلام")
    window.chat_page.send_button.click()
    assert wait_for(lambda: not window.chat_page.is_busy)

    window.show_page("dashboard")
    assert dashboard.chats_card.value_label.text() == "1"
    assert dashboard.messages_card.value_label.text() == "2"
    assert dashboard.empty_label.isHidden() is True
    assert len(dashboard._rows) == 1

    # دکمه «بازکردن» باید به صفحه چت برگرداند و همان گفتگو را باز کند.
    open_button = open_buttons_of(dashboard)[0]
    open_button.click()

    assert window.page_stack.currentWidget() is window.chat_page
    assert window.chat_page.current_conversation_id is not None

    # دکمه «گفتگوی جدید» داشبورد گفتگو را خالی می‌کند.
    window.show_page("dashboard")
    window.dashboard_page.new_chat_button.click()

    assert window.page_stack.currentWidget() is window.chat_page
    assert window.chat_page.current_conversation_id is None

    window.close()
