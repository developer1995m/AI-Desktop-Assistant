"""تست‌های جست‌وجوی سراسری."""

import pytest

from PySide6.QtGui import QShortcut

from app.services.storage import ConversationStore, snippet_from
from app.ui.widgets.search_dialog import SearchDialog

from tests.test_main_window import make_window


@pytest.fixture
def store(tmp_path):
    """پایگاه‌داده پر از داده در همه بخش‌ها."""
    database = ConversationStore(tmp_path / "assistant.db")
    conversation_id = database.create_conversation("گفتگو درباره پایتون")
    database.add_exchange(conversation_id, "پایتون چیست؟", "یک زبان برنامه‌نویسی است.")
    database.create_note("خرید هفتگی", "نان و پنیر و Python برای تمرین")
    database.create_task("تمرین پایتون", "high")
    database.add_memory("من با Python کار می‌کنم")

    yield database
    database.close()


# ------------------------------------------------------------------ در پایگاه‌داده


def test_search_finds_every_kind(store):
    hits = store.search("پایتون")

    assert [hit.kind for hit in hits] == ["conversation", "task"]
    assert hits[0].title == "گفتگو درباره پایتون"
    assert hits[0].snippet == "پایتون چیست؟"
    assert hits[1].snippet == "در انتظار • مهم"


def test_search_finds_notes_by_title_and_body(store):
    by_title = store.search("خرید")
    by_body = store.search("پنیر")

    assert [(hit.kind, hit.id) for hit in by_title] == [("note", 1)]
    assert by_title[0].snippet == "نان و پنیر و Python برای تمرین"
    assert [hit.kind for hit in by_body] == ["note"]


def test_search_is_case_insensitive_for_ascii(store):
    assert [hit.kind for hit in store.search("python")] == ["note", "memory"]
    assert [hit.kind for hit in store.search("PYTHON")] == ["note", "memory"]


def test_search_matches_messages_inside_conversation(store):
    hits = store.search("زبان برنامه‌نویسی")

    assert [hit.kind for hit in hits] == ["conversation"]
    assert "زبان برنامه‌نویسی" in hits[0].snippet


def test_search_reports_disabled_memories(store):
    memory_id = store.add_memory("رمز من ۱۲۳۴ است")
    store.set_memory_enabled(memory_id, False)

    hit = store.search("رمز")[0]

    assert (hit.kind, hit.id, hit.snippet) == ("memory", memory_id, "غیرفعال")


def test_search_ignores_blank_query(store):
    assert store.search("") == []
    assert store.search("   ") == []


def test_search_without_matches_returns_empty(store):
    assert store.search("این عبارت وجود ندارد") == []


def test_search_escapes_like_wildcards(store):
    """درصد و زیرخط باید متن ساده باشند، نه الگوی LIKE."""
    store.create_note("درصد", "تخفیف ۵۰٪ و 100% واقعی")

    # اگر علائم فرار اعمال نشود، «%» همه ردیف‌ها را برمی‌گرداند.
    assert [hit.title for hit in store.search("%")] == ["درصد"]
    assert store.search("_") == []
    assert [hit.title for hit in store.search("100%")] == ["درصد"]


def test_search_limits_results_per_kind(tmp_path):
    database = ConversationStore(tmp_path / "many.db")

    try:
        for index in range(8):
            database.create_note(f"یادداشت شماره {index}", "همه یک کلمه مشترک دارند")

        assert len(database.search("مشترک")) == 5
        assert len(database.search("مشترک", limit_per_kind=2)) == 2
    finally:
        database.close()


def test_snippet_marks_the_cut_edges():
    text = "x" * 200 + " نشانه " + "y" * 200

    snippet = snippet_from(text, "نشانه")

    assert snippet.startswith("…")
    assert snippet.endswith("…")
    assert "نشانه" in snippet
    assert len(snippet) < len(text)


def test_snippet_without_match_is_clipped():
    snippet = snippet_from("z" * 500, "نبوده")

    assert snippet.endswith("…")
    assert len(snippet) <= 121


def test_snippet_collapses_whitespace():
    assert snippet_from("خط اول\n\n   خط دوم", "دوم") == "خط اول خط دوم"


def test_snippet_of_empty_text():
    assert snippet_from("", "چیزی") == ""


# ------------------------------------------------------------------ پنجره جست‌وجو


def test_dialog_groups_results_by_section(qt_app, store):
    dialog = SearchDialog(store)

    try:
        dialog.search_input.setText("پایتون")
        dialog.refresh()

        assert "2 نتیجه" in dialog.hint_label.text()
        assert len(dialog._rows) == 2
        labels = [
            dialog.results_layout.itemAt(index).widget().text()
            for index in range(dialog.results_layout.count() - 1)
            if dialog.results_layout.itemAt(index).widget() is not None
        ]
        assert "گفتگوها" in labels
        assert "وظیفه‌ها" in labels
    finally:
        dialog.deleteLater()


def test_dialog_shows_hints_for_empty_and_missing_results(qt_app, store):
    dialog = SearchDialog(store)

    try:
        assert dialog.hint_label.text().startswith("برای جست‌وجو")

        dialog.search_input.setText("پیدا نمی‌شود")
        assert dialog.hint_label.text() == "چیزی پیدا نشد."

        # نوشتن دوباره باید نتیجه‌های قبلی را پاک کند، نه اینکه روی آن‌ها اضافه شود.
        dialog.search_input.setText("پایتون")
        dialog.refresh()
        assert len(dialog._rows) == 2

        dialog.search_input.setText("خرید")
        dialog.refresh()
        assert len(dialog._rows) == 1
    finally:
        dialog.deleteLater()


def test_dialog_emits_selected_result(qt_app, store):
    dialog = SearchDialog(store)
    selected: list[tuple[str, int]] = []
    dialog.result_selected.connect(lambda kind, item_id: selected.append((kind, item_id)))

    try:
        dialog.search_input.setText("پنیر")
        dialog.refresh()
        dialog._rows[0].click()

        assert selected == [("note", 1)]
        assert dialog.result() == SearchDialog.DialogCode.Accepted
    finally:
        dialog.deleteLater()


def test_dialog_survives_closed_database(qt_app, store):
    """اگر پایگاه‌داده بسته باشد، پنجره باید پیام خطا نشان دهد نه اینکه بترکد."""
    dialog = SearchDialog(store)

    try:
        store.close()
        dialog.search_input.setText("پایتون")
        dialog.refresh()

        assert "ناموفق" in dialog.hint_label.text()
    finally:
        dialog.deleteLater()


# ------------------------------------------------------------- پیمایش از پنجره اصلی


def test_search_result_navigation(qt_app, tmp_path, monkeypatch):
    store = ConversationStore(tmp_path / "chat.db")
    conversation_id = store.create_conversation("گفتگوی مقصد")
    store.add_exchange(conversation_id, "سلام", "سلام!")
    note_id = store.create_note("یادداشت مقصد", "متن")
    store.create_task("وظیفه مقصد")
    store.add_memory("نام من مسعود است")

    window = make_window(qt_app, tmp_path, monkeypatch, store=store)
    window.show()

    try:
        window.open_search_result("note", note_id)
        assert window.page_stack.currentWidget() is window.notes_page
        assert window.notes_page.title_input.text() == "یادداشت مقصد"

        window.open_search_result("task", 1)
        assert window.page_stack.currentWidget() is window.tasks_page

        window.open_search_result("memory", 1)
        assert window.page_stack.currentWidget() is window.memory_page

        window.open_search_result("conversation", conversation_id)
        assert window.page_stack.currentWidget() is window.chat_page
        assert window.chat_page.current_conversation_id == conversation_id
    finally:
        window.close()
        window.deleteLater()


def test_header_button_opens_search_dialog(qt_app, tmp_path, monkeypatch):
    window = make_window(qt_app, tmp_path, monkeypatch)
    window.show()

    try:
        # exec روی گفت‌وگو متوقف می‌شود؛ فقط ساخت و باز شدن آن بررسی می‌شود.
        monkeypatch.setattr(SearchDialog, "exec", lambda self: 0)
        window.search_button.click()

        assert isinstance(window.search_dialog, SearchDialog)
        assert window.search_dialog.parent() is window
        assert "Ctrl+K" in window.search_button.text()

        # میان‌بر صفحه‌کلید هم به همان مسیر وصل است.
        shortcuts = [
            shortcut
            for shortcut in window.findChildren(QShortcut)
            if shortcut.key().toString() == "Ctrl+K"
        ]
        assert shortcuts
    finally:
        window.close()
        window.deleteLater()
