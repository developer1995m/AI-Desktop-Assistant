"""تست‌های بخش گفتگوهای نوار کناری."""

from app.services.storage import Conversation
from app.ui.widgets.conversation_list import ConversationList
from app.ui.widgets.sidebar import Sidebar


def make_conversation(conversation_id: int, title: str) -> Conversation:
    """یک گفتگوی نمونه برای تست می‌سازد."""
    return Conversation(
        id=conversation_id,
        title=title,
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
    )


def test_conversation_list_marks_active_conversation(qt_app):
    widget = ConversationList()
    widget.set_conversations(
        [make_conversation(1, "اول"), make_conversation(2, "دوم")], active_id=2
    )

    assert list(widget.buttons) == [1, 2]
    assert widget.buttons[2].isChecked() is True
    assert widget.buttons[1].isChecked() is False
    assert widget.empty_label.isHidden() is True
    assert widget.buttons[1].text() == "اول"


def test_conversation_list_emits_selection_and_delete(qt_app):
    widget = ConversationList()
    widget.set_conversations([make_conversation(1, "اول")], active_id=None)

    selected: list[int] = []
    delete_requested: list[int] = []
    widget.conversation_selected.connect(selected.append)
    widget.conversation_delete_requested.connect(delete_requested.append)

    widget.buttons[1].click()
    widget.delete_buttons[1].click()

    assert selected == [1]
    assert delete_requested == [1]


def test_conversation_list_shows_hint_when_empty(qt_app):
    widget = ConversationList()
    widget.set_conversations([make_conversation(1, "اول")], active_id=1)
    assert widget.empty_label.isHidden() is True

    widget.set_conversations([], active_id=None)

    assert widget.buttons == {}
    assert widget.empty_label.isHidden() is False


def test_sidebar_shows_conversations_only_on_chat_page(qt_app):
    sidebar = Sidebar()
    sidebar.show()

    sidebar.set_active_page("chat")
    assert sidebar.conversations.isVisible() is True

    sidebar.set_active_page("notes")
    assert sidebar.conversations.isVisible() is False


def test_sidebar_forwards_conversation_signals(qt_app):
    sidebar = Sidebar()
    selected: list[int] = []
    sidebar.conversation_selected.connect(selected.append)

    sidebar.set_conversations([make_conversation(7, "هفتم")], active_id=7)
    sidebar.conversations.buttons[7].click()

    assert selected == [7]
