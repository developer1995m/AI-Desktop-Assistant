"""تست‌های حافظه: ذخیره‌سازی، تزریق در پرامپت و صفحه رابط کاربری."""

import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QCheckBox, QDialog, QLabel, QLineEdit, QPushButton

from app.services.chat_service import MEMORY_HEADER, ChatService, build_messages
from app.services.settings import AppSettings
from app.services.storage import MAX_MEMORY_CHARS, ConversationStore
from app.ui.pages.memory_page import MemoryPage


@pytest.fixture
def store(tmp_path):
    """یک پایگاه‌داده تازه برای هر تست می‌سازد."""
    database = ConversationStore(tmp_path / "assistant.db")
    yield database
    database.close()


# ------------------------------------------------------------------ ذخیره‌سازی


def test_add_and_list_memories(store):
    first = store.add_memory("نام من مسعود است")
    second = store.add_memory("  من   فارسی حرف می‌زنم  ")

    memories = store.list_memories()

    assert [memory.id for memory in memories] == [second, first]
    assert memories[0].content == "من فارسی حرف می‌زنم"
    assert memories[0].enabled is True


def test_memory_rejects_empty_and_long_text(store):
    with pytest.raises(ValueError):
        store.add_memory("   ")

    with pytest.raises(ValueError):
        store.add_memory("x" * (MAX_MEMORY_CHARS + 1))


def test_update_and_toggle_memory(store):
    memory_id = store.add_memory("نام من مسعود است")

    store.update_memory(memory_id, "نام من مسعود است و در تهران زندگی می‌کنم")
    store.set_memory_enabled(memory_id, False)

    memory = store.get_memory(memory_id)

    assert memory.content == "نام من مسعود است و در تهران زندگی می‌کنم"
    assert memory.enabled is False
    assert store.count_memories() == 1
    assert store.count_memories(only_enabled=True) == 0
    assert store.list_memories(only_enabled=True) == []


def test_memories_persist_between_sessions(tmp_path):
    database_path = tmp_path / "assistant.db"

    first_session = ConversationStore(database_path)
    first_session.add_memory("نام من مسعود است")
    first_session.close()

    second_session = ConversationStore(database_path)

    try:
        assert [memory.content for memory in second_session.list_memories()] == [
            "نام من مسعود است"
        ]
    finally:
        second_session.close()


def test_delete_memory(store):
    memory_id = store.add_memory("نام من مسعود است")

    store.delete_memory(memory_id)
    store.delete_memory(memory_id)

    assert store.get_memory(memory_id) is None
    assert store.count_memories() == 0


# ------------------------------------------------------------------- پرامپت


def test_build_messages_injects_memories_once():
    messages = build_messages(
        [{"role": "user", "content": "سلام"}, {"role": "assistant", "content": "سلام!"}],
        "اسم من چیه؟",
        memories=["نام من مسعود است", "  ", "فارسی حرف می‌زنم"],
    )

    system_content = messages[0]["content"]

    assert MEMORY_HEADER in system_content
    assert "- نام من مسعود است" in system_content
    assert "- فارسی حرف می‌زنم" in system_content
    assert system_content.count("نام من مسعود است") == 1
    assert messages[-1] == {"role": "user", "content": "اسم من چیه؟"}


def test_build_messages_without_memories_keeps_system_prompt():
    messages = build_messages([], "سلام", memories=[])

    assert MEMORY_HEADER not in messages[0]["content"]


def test_service_reads_only_enabled_memories(store, tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    enabled_id = store.add_memory("نام من مسعود است")
    disabled_id = store.add_memory("رمز عبورم ۱۲۳۴ است")
    store.set_memory_enabled(disabled_id, False)

    service = ChatService(AppSettings(tmp_path / "missing.env"), store)

    assert service.active_memories() == ["نام من مسعود است"]
    assert store.get_memory(enabled_id) is not None


def test_service_without_store_has_no_memories(tmp_path):
    assert ChatService(AppSettings(tmp_path / "missing.env")).active_memories() == []


# ------------------------------------------------------------ صفحه رابط کاربری


def _row_texts(page) -> list[str]:
    """متن همه ردیف‌های حافظه را برمی‌گرداند."""
    return [
        label.text()
        for row in page._rows
        for label in row.findChildren(QLabel)
        if label.objectName() == "memoryContent"
    ]


def test_memory_page_lists_saved_memories(qt_app, store):
    store.add_memory("نام من مسعود است")
    store.add_memory("من فارسی حرف می‌زنم")
    page = MemoryPage(store)

    try:
        page.refresh()

        assert page.counter_label.text() == "2 فعال از 2 واقعیت"
        assert _row_texts(page) == ["من فارسی حرف می‌زنم", "نام من مسعود است"]
    finally:
        page.deleteLater()


def test_memory_page_shows_empty_state(qt_app, store):
    page = MemoryPage(store)

    try:
        assert page.empty_label.isVisibleTo(page)
        assert page._rows == []
    finally:
        page.deleteLater()


def test_memory_page_hides_checkbox_state_of_disabled_memory(qt_app, store):
    memory_id = store.add_memory("نام من مسعود است")
    store.set_memory_enabled(memory_id, False)
    page = MemoryPage(store)

    try:
        page.refresh()

        checkbox = page._rows[0].findChildren(QCheckBox)[0]

        assert checkbox.isChecked() is False
    finally:
        page.deleteLater()


def test_memory_page_adds_memory(qt_app, store):
    page = MemoryPage(store)
    changes: list[bool] = []
    page.memories_changed.connect(lambda: changes.append(True))

    try:
        page.content_input.setText("  نام من مسعود است  ")
        page.add_button.click()

        memories = store.list_memories()

        assert [memory.content for memory in memories] == ["نام من مسعود است"]
        assert page.content_input.text() == ""
        assert changes == [True]
        assert page.counter_label.text() == "1 فعال از 1 واقعیت"
    finally:
        page.deleteLater()


def test_memory_page_ignores_blank_input(qt_app, store):
    page = MemoryPage(store)

    try:
        page.content_input.setText("   ")
        page.add_button.click()

        assert store.count_memories() == 0
    finally:
        page.deleteLater()


def test_memory_page_toggle_updates_counter(qt_app, store):
    memory_id = store.add_memory("نام من مسعود است")
    page = MemoryPage(store)

    try:
        page._toggle_memory(memory_id, False)

        assert store.get_memory(memory_id).enabled is False
        assert page.counter_label.text() == "0 فعال از 1 واقعیت"
    finally:
        page.deleteLater()


def test_memory_page_delete_requires_confirmation(qt_app, store, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    memory_id = store.add_memory("نام من مسعود است")
    page = MemoryPage(store)

    try:
        monkeypatch.setattr(
            QMessageBox,
            "question",
            staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.No),
        )
        page._delete_memory(memory_id)
        assert store.count_memories() == 1

        monkeypatch.setattr(
            QMessageBox,
            "question",
            staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.Yes),
        )
        page._delete_memory(memory_id)
        assert store.count_memories() == 0
    finally:
        page.deleteLater()


def test_memory_page_edit_saves_changes_from_dialog(qt_app, store):
    memory_id = store.add_memory("نام من مسعود است")
    page = MemoryPage(store)
    changes: list[bool] = []
    page.memories_changed.connect(lambda: changes.append(True))

    def save_edit():
        dialog = qt_app.activeModalWidget()
        assert isinstance(dialog, QDialog)
        dialog.findChild(QLineEdit, "memoryEditInput").setText("نام من سارا است")
        dialog.findChild(QPushButton, "memoryEditSaveButton").click()

    try:
        QTimer.singleShot(0, save_edit)
        page._edit_memory(memory_id)

        assert store.get_memory(memory_id).content == "نام من سارا است"
        assert _row_texts(page) == ["نام من سارا است"]
        assert changes == [True]
    finally:
        page.deleteLater()


def test_memory_page_edit_cancel_keeps_original_value(qt_app, store):
    memory_id = store.add_memory("نام من مسعود است")
    page = MemoryPage(store)

    def cancel_edit():
        dialog = qt_app.activeModalWidget()
        assert isinstance(dialog, QDialog)
        dialog.findChild(QLineEdit, "memoryEditInput").setText("متن موقت")
        dialog.findChild(QPushButton, "memoryEditCancelButton").click()

    try:
        QTimer.singleShot(0, cancel_edit)
        page._edit_memory(memory_id)

        assert store.get_memory(memory_id).content == "نام من مسعود است"
        assert _row_texts(page) == ["نام من مسعود است"]
    finally:
        page.deleteLater()
