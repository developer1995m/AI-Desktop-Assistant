"""تست‌های ذخیره‌سازی یادداشت‌ها و صفحه Notes."""

import pytest
from PySide6.QtWidgets import QLabel, QMessageBox, QPushButton

from app.services.storage import ConversationStore
from app.ui.main_window import MainWindow
from app.ui.pages.chat_page import ChatPage
from app.ui.pages.dashboard_page import DashboardPage
from app.ui.pages.memory_page import MemoryPage
from app.ui.pages.notes_page import NotesPage, preview_text
from app.ui.pages.pdf_page import PdfPage
from app.ui.pages.settings_page import SettingsPage
from app.ui.pages.tasks_page import TasksPage
from app.ui.pages.help_page import HelpPage

from tests.test_main_window import make_window


def make_notes_page(tmp_path):
    store = ConversationStore(tmp_path / "chat.db")
    return store, NotesPage(store)


def note_row_buttons(page, row_index: int, label: str) -> list[QPushButton]:
    """دکمه‌های یک لیبل مشخص در ردیف یادداشت را برمی‌گرداند."""
    row = page._rows[row_index]

    return [
        button for button in row.findChildren(QPushButton) if button.text() == label
    ]


def test_note_crud_round_trip(tmp_path):
    store = ConversationStore(tmp_path / "chat.db")

    note_id = store.create_note("خرید", "نان و پنیر")
    assert store.count_notes() == 1

    note = store.get_note(note_id)
    assert note.title == "خرید"
    assert note.content == "نان و پنیر"

    store.update_note(note_id, "لیست خرید", "نان، پنیر و چای")
    updated = store.get_note(note_id)
    assert updated.title == "لیست خرید"
    assert updated.content == "نان، پنیر و چای"
    assert updated.updated_at >= note.created_at

    store.delete_note(note_id)
    assert store.count_notes() == 0
    assert store.get_note(note_id) is None


def test_list_notes_orders_by_recent_update(tmp_path):
    store = ConversationStore(tmp_path / "chat.db")
    first = store.create_note("اول", "الف")
    second = store.create_note("دوم", "ب")

    assert [note.id for note in store.list_notes()] == [second, first]

    store.update_note(first, "اول", "متن تازه")

    assert [note.id for note in store.list_notes()] == [first, second]


def test_note_title_is_normalised(tmp_path):
    store = ConversationStore(tmp_path / "chat.db")

    note_id = store.create_note("   متن   بلند   برای   عنوان   ")
    note = store.get_note(note_id)
    assert note.title == "متن بلند برای عنوان"


def test_preview_text_rules():
    assert preview_text("") == "—"
    assert preview_text("  خط اول\nخط دوم  ") == "خط اول خط دوم"

    long_preview = preview_text("م" * 200, max_length=30)
    assert len(long_preview) == 30
    assert long_preview.endswith("…")


def test_notes_page_starts_empty(qt_app, tmp_path):
    store, page = make_notes_page(tmp_path)
    page.show()

    assert page._rows == []
    assert page.empty_label.isVisible() is True
    assert page.mode_stack.currentWidget() is page.list_view


def test_create_note_from_editor(qt_app, tmp_path):
    store, page = make_notes_page(tmp_path)
    page.show()

    page.new_note_button.click()
    assert page.mode_stack.currentWidget() is page.editor
    assert page.delete_button.isVisible() is False  # یادداشت جدید هنوز حذف ندارد

    page.title_input.setText("یادداشت اول")
    page.content_input.setPlainText("متن یادداشت")
    page.save_button.click()

    assert store.count_notes() == 1
    assert page.mode_stack.currentWidget() is page.list_view
    assert len(page._rows) == 1


def test_edit_existing_note(qt_app, tmp_path):
    store, page = make_notes_page(tmp_path)
    note_id = store.create_note("عنوان قدیمی", "متن قدیمی")
    page.refresh()
    page.show()

    assert len(page._rows) == 1
    note_row_buttons(page, 0, "بازکردن")[0].click()
    assert page.mode_stack.currentWidget() is page.editor
    assert page.title_input.text() == "عنوان قدیمی"
    assert page.content_input.toPlainText() == "متن قدیمی"
    assert page.delete_button.isVisibleTo(page.editor) is True

    page.title_input.setText("عنوان تازه")
    page.save_button.click()

    assert store.get_note(note_id).title == "عنوان تازه"
    assert page.mode_stack.currentWidget() is page.list_view


def test_delete_note_with_confirmation(qt_app, tmp_path, monkeypatch):
    store, page = make_notes_page(tmp_path)
    note_id = store.create_note("حذف‌شدنی", "متن")
    page.refresh()
    page.show()

    monkeypatch.setattr(
        QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.No
    )
    note_row_buttons(page, 0, "حذف")[0].click()
    assert store.count_notes() == 1

    monkeypatch.setattr(
        QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Yes
    )
    note_row_buttons(page, 0, "حذف")[0].click()

    assert store.count_notes() == 0
    assert page._rows == []
    assert page.empty_label.isVisible() is True


def test_back_button_discards_unsaved_editor(qt_app, tmp_path):
    store, page = make_notes_page(tmp_path)
    store.create_note("ماندنی", "متن")
    page.show()

    page.new_note_button.click()
    page.title_input.setText("ذخیره نشده")
    page.back_button.click()

    assert store.count_notes() == 1
    assert page.mode_stack.currentWidget() is page.list_view


def test_empty_editor_is_rejected(qt_app, tmp_path):
    store, page = make_notes_page(tmp_path)
    page.show()

    page.new_note_button.click()
    page.save_button.click()

    assert store.count_notes() == 0
    assert page.mode_stack.currentWidget() is page.editor


def test_main_window_notes_page_syncs_dashboard(qt_app, tmp_path, monkeypatch):
    window = make_window(qt_app, tmp_path, monkeypatch)
    window.show()
    window.show_page("notes")

    window.notes_page.new_note_button.click()
    window.notes_page.title_input.setText("از پنجره اصلی")
    window.notes_page.content_input.setPlainText("متن")
    window.notes_page.save_button.click()

    assert window.dashboard_page.chats_card.value_label.text() == "0"

    # داشبورد پس از تغییر یادداشت‌ها هم تازه می‌شود (شمارش یادداشت‌ها فعلاً جدا است).
    window.show_page("notes")
    window.notes_page.new_note_button.click()
    window.notes_page.title_input.setText("دوم")
    window.notes_page.save_button.click()

    assert window.chat_store.count_notes() == 2

    window.close()


# --------------------------------------------------------------------- برچسب‌ها


def test_tags_round_trip_through_the_editor(qt_app, tmp_path):
    store, page = make_notes_page(tmp_path)

    page.show_editor(None)
    page.title_input.setText("لیست خرید")
    page.content_input.setPlainText("نان و پنیر")
    page.tags_input.setText("خرید, خانه, خرید")
    page.save_button.click()

    note = store.list_notes()[0]
    assert note.tags == ("خرید", "خانه")

    # باز کردن دوباره یادداشت، برچسب‌ها را به ویرایشگر برمی‌گرداند.
    page.show_editor(note)
    assert page.tags_input.text() == "خرید, خانه"


def test_editor_clears_tags_for_a_new_note(qt_app, tmp_path):
    store, page = make_notes_page(tmp_path)
    store.create_note("دارای برچسب", "متن", tags="کار")
    page.show_editor(store.list_notes()[0])
    assert page.tags_input.text() == "کار"

    page.show_editor(None)
    assert page.tags_input.text() == ""


def tag_chips_of(row) -> list[str]:
    """متن چیپ‌های برچسب یک ردیف."""
    return [
        label.text()
        for label in row.findChildren(QLabel)
        if label.objectName() == "tagChip"
    ]


def test_rows_show_a_chip_per_tag(qt_app, tmp_path):
    store, page = make_notes_page(tmp_path)
    store.create_note("با برچسب", "متن", tags="کار, خانه")
    store.create_note("بی‌برچسب", "متن")
    page.refresh()

    rows = {row.findChild(QLabel, "noteRowTitle").text(): row for row in page._rows}

    assert tag_chips_of(rows["با برچسب"]) == ["کار", "خانه"]
    assert tag_chips_of(rows["بی‌برچسب"]) == []


def test_tag_filter_narrows_the_list_and_the_counter(qt_app, tmp_path):
    store, page = make_notes_page(tmp_path)
    store.create_note("کاری", "متن", tags="کار")
    store.create_note("خانه‌ای", "متن", tags="خانه")
    store.create_note("بی‌برچسب", "متن")
    page.refresh()

    assert page.filter_bar.isVisibleTo(page) is True
    assert page.notes_counter.text() == "3 یادداشت"
    assert page.tag_filter.count() == 3  # همه + دو برچسب

    page.tag_filter.setCurrentIndex(page.tag_filter.findData("کار"))

    assert len(page._rows) == 1
    assert page.notes_counter.text() == "1 از 3 یادداشت"
    assert tag_chips_of(page._rows[0]) == ["کار"]

    page.tag_filter.setCurrentIndex(0)
    assert len(page._rows) == 3
    assert page.notes_counter.text() == "3 یادداشت"


def test_tag_filter_keeps_its_choice_after_a_save(qt_app, tmp_path):
    store, page = make_notes_page(tmp_path)
    store.create_note("کاری", "متن", tags="کار")
    store.create_note("بی‌برچسب", "متن")
    page.refresh()
    page.tag_filter.setCurrentIndex(page.tag_filter.findData("کار"))

    page.show_editor(None)
    page.title_input.setText("کار تازه")
    page.content_input.setPlainText("متن")
    page.tags_input.setText("کار")
    page.save_button.click()

    assert page.selected_tag() == "کار"
    assert len(page._rows) == 2
    assert page.notes_counter.text() == "2 از 3 یادداشت"


def test_filter_bar_hides_when_no_tag_exists(qt_app, tmp_path):
    store, page = make_notes_page(tmp_path)
    note_id = store.create_note("با برچسب", "متن", tags="کار")
    page.refresh()
    assert page.filter_bar.isVisibleTo(page) is True

    store.update_note(note_id, "بدون برچسب", "متن")
    page.refresh()

    assert page.filter_bar.isVisibleTo(page) is False
    assert page.selected_tag() == ""
    assert len(page._rows) == 1


def test_note_search_finds_a_tag_only_match(qt_app, tmp_path):
    store, page = make_notes_page(tmp_path)
    store.create_note("برنامه هفته", "متن نامرتبط", tags="پروژه‌آلفا")

    hits = store.search("پروژه‌آلفا")

    assert len(hits) == 1
    assert "پروژه‌آلفا" in hits[0].snippet


def test_no_placeholder_pages_remain(qt_app, tmp_path, monkeypatch):
    """هیچ صفحه‌ای نباید هنوز نمونه آزمایشی/Placeholder باشد."""
    window = make_window(qt_app, tmp_path, monkeypatch)

    real_page_types = (
    ChatPage,
    DashboardPage,
    SettingsPage,
    NotesPage,
    TasksPage,
    MemoryPage,
    PdfPage,
    HelpPage,
    )

    # هر صفحه‌ای که در سایدبار هست باید نمونه واقعی خودش باشد، نه Placeholder موقت.
    for page_key, index in window.page_indexes.items():
        assert isinstance(window.page_stack.widget(index), real_page_types), page_key

    window.close()
