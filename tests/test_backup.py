"""تست‌های پشتیبان‌گیری و بازیابی داده‌ها."""

import json

import pytest

from app.services.backup import (
    AUTO_BACKUP_KEEP,
    BACKUP_FORMAT,
    BACKUP_VERSION,
    BackupError,
    auto_backup,
    default_backup_folder,
    default_backup_name,
    export_backup,
    import_backup,
    list_backups,
    prune_backups,
    read_backup,
    summarise,
)
from app.services.storage import ConversationStore
from app.ui import main_window as main_window_module
from app.ui.pages.settings_page import SettingsPage
from app.ui.widgets.chat_bubble import MessageBubble


@pytest.fixture
def store(tmp_path):
    """پایگاه‌داده تازه برای هر تست."""
    database = ConversationStore(tmp_path / "assistant.db")
    yield database
    database.close()


@pytest.fixture
def filled_store(store):
    """پایگاه‌داده‌ای پر از داده در هر چهار بخش."""
    conversation_id = store.create_conversation("گفتگو درباره پایتون")
    store.add_exchange(conversation_id, "پایتون چیست؟", "یک زبان برنامه‌نویسی است.")
    store.create_note("خرید", "نان و پنیر")
    store.create_task("تماس با پزشک", "high")
    store.add_memory("نام من مسعود است")

    return store


# --------------------------------------------------------------------- پشتیبان


def test_export_writes_versioned_json(filled_store, tmp_path):
    path = export_backup(filled_store, tmp_path / "backup.json")

    payload = json.loads(path.read_text(encoding="utf-8"))

    assert payload["format"] == BACKUP_FORMAT
    assert payload["version"] == BACKUP_VERSION
    assert payload["created_at"]
    assert len(payload["tables"]["conversations"]) == 1
    assert len(payload["tables"]["messages"]) == 2
    assert len(payload["tables"]["notes"]) == 1
    assert len(payload["tables"]["tasks"]) == 1
    assert len(payload["tables"]["memories"]) == 1


def test_export_creates_missing_folders(filled_store, tmp_path):
    path = export_backup(filled_store, tmp_path / "deep" / "nested" / "backup.json")

    assert path.is_file()


def test_export_includes_persian_text_without_escaping(filled_store, tmp_path):
    path = export_backup(filled_store, tmp_path / "backup.json")

    content = path.read_text(encoding="utf-8")

    assert "نام من مسعود است" in content


# ---------------------------------------------------------------------- خواندن


def test_read_backup_round_trips_all_tables(filled_store, tmp_path):
    path = export_backup(filled_store, tmp_path / "backup.json")

    tables = read_backup(path)

    assert [row["title"] for row in tables["notes"]] == ["خرید"]
    assert [row["content"] for row in tables["memories"]] == ["نام من مسعود است"]
    assert {row["role"] for row in tables["messages"]} == {"user", "assistant"}


def test_read_backup_reports_missing_file(tmp_path):
    with pytest.raises(BackupError) as error:
        read_backup(tmp_path / "nope.json")

    assert "پیدا نشد" in str(error.value)


def test_read_backup_reports_invalid_json(tmp_path):
    path = tmp_path / "broken.json"
    path.write_text("{not json", encoding="utf-8")

    with pytest.raises(BackupError) as error:
        read_backup(path)

    assert "JSON" in str(error.value)


def test_read_backup_rejects_other_json_files(tmp_path):
    path = tmp_path / "other.json"
    path.write_text(json.dumps({"hello": "world"}), encoding="utf-8")

    with pytest.raises(BackupError):
        read_backup(path)


def test_read_backup_rejects_newer_version(tmp_path):
    path = tmp_path / "future.json"
    path.write_text(
        json.dumps(
            {
                "format": BACKUP_FORMAT,
                "version": BACKUP_VERSION + 1,
                "tables": {"notes": [{"id": 1}]},
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(BackupError) as error:
        read_backup(path)

    assert "جدیدتری" in str(error.value)


def test_read_backup_rejects_unknown_tables(tmp_path):
    path = tmp_path / "alien.json"
    path.write_text(
        json.dumps(
            {
                "format": BACKUP_FORMAT,
                "version": BACKUP_VERSION,
                "tables": {"unknown_table": [{"id": 1}]},
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(BackupError):
        read_backup(path)


def test_read_backup_rejects_empty_payload(tmp_path):
    path = tmp_path / "empty.json"
    path.write_text(
        json.dumps({"format": BACKUP_FORMAT, "version": BACKUP_VERSION, "tables": {}}),
        encoding="utf-8",
    )

    with pytest.raises(BackupError):
        read_backup(path)


def test_missing_tables_are_treated_as_empty(tmp_path):
    path = tmp_path / "partial.json"
    path.write_text(
        json.dumps(
            {
                "format": BACKUP_FORMAT,
                "version": BACKUP_VERSION,
                "tables": {"notes": [{"id": 3, "title": "تنها"}]},
            }
        ),
        encoding="utf-8",
    )

    tables = read_backup(path)

    assert [row["title"] for row in tables["notes"]] == ["تنها"]
    assert tables["conversations"] == []
    assert tables["memories"] == []


# -------------------------------------------------------------------- بازیابی


def test_import_restores_identical_data(filled_store, tmp_path):
    path = export_backup(filled_store, tmp_path / "backup.json")
    expected = filled_store.snapshot()

    target = ConversationStore(tmp_path / "target.db")

    try:
        counts = import_backup(target, path)

        assert counts["conversations"] == 1
        assert counts["messages"] == 2
        assert counts["notes"] == 1
        assert counts["tasks"] == 1
        assert counts["memories"] == 1
        # شناسه‌ها و زمان‌ها دست‌نخورده برمی‌گردند تا ترتیب گفتگوها حفظ شود.
        assert target.snapshot() == expected
    finally:
        target.close()


def test_import_replaces_existing_data(filled_store, tmp_path, store):
    path = export_backup(filled_store, tmp_path / "backup.json")

    store.create_note("یادداشت موقت", "باید پاک شود")
    store.create_conversation("گفتگوی موقت")

    import_backup(store, path)

    assert [note.title for note in store.list_notes()] == ["خرید"]
    assert [conversation.title for conversation in store.list_conversations()] == [
        "گفتگو درباره پایتون"
    ]
    assert store.count_notes() == 1


def test_import_of_empty_backup_clears_data(filled_store, tmp_path, store):
    path = tmp_path / "empty.json"
    path.write_text(
        json.dumps({"format": BACKUP_FORMAT, "version": BACKUP_VERSION, "tables": {"notes": []}}),
        encoding="utf-8",
    )

    import_backup(store, path)

    assert store.count_notes() == 0
    assert store.count_memories() == 0
    assert store.stats().conversation_count == 0


def test_import_reports_invalid_rows_without_touching_data(filled_store, tmp_path, store):
    path = tmp_path / "broken_rows.json"
    path.write_text(
        json.dumps(
            {
                "format": BACKUP_FORMAT,
                "version": BACKUP_VERSION,
                # این ردیف ستون اجباری title را ندارد.
                "tables": {"notes": [{"id": 1, "content": "بدون عنوان"}]},
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(BackupError):
        import_backup(store, path)

    # تراکنش برگشت خورده است و داده‌های قبلی سر جای خود هستند.
    assert store.count_notes() == 1
    assert store.list_notes()[0].title == "خرید"


def test_import_keeps_state_after_failed_restore(filled_store, tmp_path, store):
    path = export_backup(filled_store, tmp_path / "backup.json")
    store.add_memory("این حافظه باید در جای خود بماند")

    with pytest.raises(BackupError):
        import_backup(store, tmp_path / "missing.json")

    # هیچ چیزی نباید تغییر کند: نه داده‌های قبلی، نه داده تازه‌ای که بعد از پشتیبان اضافه شد.
    assert [memory.content for memory in store.list_memories()] == [
        "این حافظه باید در جای خود بماند",
        "نام من مسعود است",
    ]
    assert path.is_file()


# --------------------------------------------------------------------- خلاصه


def test_summarise_lists_non_empty_tables(filled_store, tmp_path):
    path = export_backup(filled_store, tmp_path / "backup.json")

    text = summarise(read_backup(path))

    assert "1 گفتگو" in text
    assert "2 پیام" in text
    assert "1 یادداشت" in text
    assert "1 وظیفه" in text
    assert "1 حافظه" in text


def test_summarise_of_empty_tables():
    assert summarise({}) == "بدون داده"


def test_default_backup_name_is_dated_json():
    name = default_backup_name()

    assert name.startswith("assistant-backup-")
    assert name.endswith(".json")
    assert len(name) == len("assistant-backup-YYYYMMDD.json")


# ------------------------------------------------------------ صفحه تنظیمات


def test_settings_page_exports_and_reports(qt_app, filled_store, tmp_path):
    page = SettingsPage(store=filled_store, settings=_settings(tmp_path))

    try:
        assert page.export_to(tmp_path / "from-page.json") is True
        assert "پشتیبان ساخته شد" in page.data_status_label.text()
        assert (tmp_path / "from-page.json").is_file()
    finally:
        page.deleteLater()


def test_settings_page_restores_and_signals(qt_app, filled_store, tmp_path):
    backup_path = export_backup(filled_store, tmp_path / "backup.json")
    page = SettingsPage(store=filled_store, settings=_settings(tmp_path))
    signals: list[bool] = []
    page.data_restored.connect(lambda: signals.append(True))

    try:
        filled_store.create_note("پاک‌شدنی", "…")
        assert page.restore_from(backup_path) is True

        assert signals == [True]
        assert [note.title for note in filled_store.list_notes()] == ["خرید"]
        assert "بازیابی انجام شد" in page.data_status_label.text()
    finally:
        page.deleteLater()


def test_settings_page_keeps_data_when_restore_fails(qt_app, filled_store, tmp_path):
    page = SettingsPage(store=filled_store, settings=_settings(tmp_path))
    signals: list[bool] = []
    page.data_restored.connect(lambda: signals.append(True))

    try:
        assert page.restore_from(tmp_path / "missing.json") is False
        assert signals == []
        assert "پیدا نشد" in page.data_status_label.text()
        assert filled_store.count_notes() == 1
    finally:
        page.deleteLater()


def test_backup_button_uses_the_file_dialog(qt_app, filled_store, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog

    page = SettingsPage(store=filled_store, settings=_settings(tmp_path))
    chosen = tmp_path / "dialog-backup.json"
    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        staticmethod(lambda *args, **kwargs: (str(chosen), "JSON (*.json)")),
    )

    try:
        page.backup_button.click()

        assert chosen.is_file()
        assert "پشتیبان ساخته شد" in page.data_status_label.text()
    finally:
        page.deleteLater()


def test_restore_button_asks_before_replacing(qt_app, filled_store, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog, QMessageBox

    backup_path = export_backup(filled_store, tmp_path / "backup.json")
    filled_store.create_note("پاک‌شدنی", "…")
    page = SettingsPage(store=filled_store, settings=_settings(tmp_path))

    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileName",
        staticmethod(lambda *args, **kwargs: (str(backup_path), "JSON (*.json)")),
    )

    try:
        # انصراف کاربر: هیچ تغییری نباید انجام شود.
        monkeypatch.setattr(
            QMessageBox,
            "question",
            staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.No),
        )
        page.restore_button.click()

        assert page.data_status_label.text() == "بازیابی لغو شد."
        assert filled_store.count_notes() == 2

        # تأیید کاربر: داده‌ها بازمی‌گردند.
        monkeypatch.setattr(
            QMessageBox,
            "question",
            staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.Yes),
        )
        page.restore_button.click()

        assert filled_store.count_notes() == 1
        assert filled_store.list_notes()[0].title == "خرید"
    finally:
        page.deleteLater()


def test_settings_page_without_store_reports_unavailable(qt_app, tmp_path):
    page = SettingsPage(settings=_settings(tmp_path))

    try:
        assert page.export_to(tmp_path / "x.json") is False
        assert "در دسترس نیست" in page.data_status_label.text()
    finally:
        page.deleteLater()


# ---------------------------------------------------------- پشتیبان خودکار


def test_auto_backup_writes_next_to_the_database(filled_store):
    path = auto_backup(filled_store)

    assert path is not None
    assert path.parent == default_backup_folder(filled_store)
    assert path.parent.parent == filled_store.database_path.parent
    assert read_backup(path)["notes"][0]["title"] == "خرید"


def test_auto_backup_skips_empty_database(store):
    assert auto_backup(store) is None
    assert list_backups(default_backup_folder(store)) == []


def test_auto_backup_names_do_not_collide(filled_store, tmp_path):
    folder = tmp_path / "auto"

    created = [auto_backup(filled_store, folder) for _ in range(3)]

    assert len({path.name for path in created if path}) == 3
    assert all(path.is_file() for path in created if path)


def test_auto_backup_keeps_only_latest_copies(filled_store, tmp_path):
    folder = tmp_path / "auto"

    created = [auto_backup(filled_store, folder) for _ in range(AUTO_BACKUP_KEEP + 3)]
    remaining = list_backups(folder)

    remaining_names = [path.name for path in remaining]

    assert len(remaining_names) == AUTO_BACKUP_KEEP
    # نام‌ها صعودی هستند و ترتیب الفبایی همان ترتیب زمانی است.
    assert remaining_names == sorted(remaining_names, reverse=True)
    # تازه‌ترین نسخه‌ها می‌مانند و سه نسخه قدیمی‌تر پاک می‌شوند.
    assert created[-1].name in remaining_names
    assert all(not path.exists() for path in created[:3])


def test_list_backups_is_empty_for_missing_folder(tmp_path):
    assert list_backups(tmp_path / "nothing") == []


def test_prune_backups_returns_removed_files(filled_store, tmp_path):
    folder = tmp_path / "auto"

    for stamp in range(4):
        export_backup(filled_store, folder / f"auto-backup-2026010{stamp}-120000.json")

    removed = prune_backups(folder, keep=2)

    assert [path.name for path in removed] == [
        "auto-backup-20260101-120000.json",
        "auto-backup-20260100-120000.json",
    ]
    assert len(list_backups(folder)) == 2


def test_closing_the_window_creates_an_automatic_backup(qt_app, tmp_path, monkeypatch):
    from tests.test_main_window import make_window

    store = ConversationStore(tmp_path / "chat.db")
    store.create_note("یادداشت", "محتوا")
    window = make_window(qt_app, tmp_path, monkeypatch, store=store)
    window.show()

    window.close()

    assert window.last_auto_backup is not None
    assert window.last_auto_backup.is_file()
    assert window.last_auto_backup.parent == tmp_path / "backups"
    assert read_backup(window.last_auto_backup)["notes"][0]["title"] == "یادداشت"

    window.deleteLater()


def test_closing_an_empty_window_does_not_write_a_backup(qt_app, tmp_path, monkeypatch):
    from tests.test_main_window import make_window

    window = make_window(qt_app, tmp_path, monkeypatch)
    window.show()

    window.close()

    assert window.last_auto_backup is None
    assert not (tmp_path / "backups").exists()

    window.deleteLater()


def test_backup_failure_never_blocks_closing(qt_app, tmp_path, monkeypatch):
    """اگر پشتیبان‌گیری خطا بدهد، بسته‌شدن پنجره باید بدون استثنا انجام شود."""
    from tests.test_main_window import make_window

    store = ConversationStore(tmp_path / "chat.db")
    store.create_note("یادداشت", "محتوا")
    window = make_window(qt_app, tmp_path, monkeypatch, store=store)
    window.show()

    def broken_backup(*args, **kwargs):
        raise BackupError("دیسک پر است")

    monkeypatch.setattr(main_window_module, "auto_backup", broken_backup)

    window.close()

    assert window.last_auto_backup is None

    window.deleteLater()


# ------------------------------------------------- اتصال به پنجره اصلی


def test_main_window_refreshes_everything_after_restore(qt_app, tmp_path, monkeypatch):
    """بازیابی پشتیبان باید همه صفحه‌ها را با داده تازه همگام کند."""
    from tests.test_main_window import make_window

    # پشتیبان شامل یک گفتگو، یک یادداشت، یک وظیفه و یک حافظه است.
    source = ConversationStore(tmp_path / "source.db")
    try:
        conversation_id = source.create_conversation("گفتگوی پشتیبان")
        source.add_exchange(conversation_id, "سؤال قدیمی", "پاسخ قدیمی")
        source.create_note("یادداشت پشتیبان", "متن یادداشت")
        source.create_task("وظیفه پشتیبان", "high")
        source.add_memory("نام من مسعود است")
        backup_path = export_backup(source, tmp_path / "window-backup.json")
    finally:
        source.close()

    window = make_window(qt_app, tmp_path, monkeypatch)
    window.show()

    try:
        assert window.chat_store.count_notes() == 0
        assert window.settings_page.restore_from(backup_path) is True

        qt_app.processEvents()

        # سایدبار و داشبورد
        assert list(window.sidebar.conversations.buttons) == [conversation_id]
        assert window.dashboard_page.chats_card.value_label.text() == "1"
        assert window.dashboard_page._rows
        # صفحه چت گفتگوی بازیابی‌شده را از پایگاه‌داده دوباره خوانده است.
        assert window.chat_page.current_conversation_id == conversation_id
        assert [bubble.text() for bubble in window.chat_page.findChildren(MessageBubble)] == [
            "سؤال قدیمی",
            "پاسخ قدیمی",
        ]
        #صفحه‌های یادداشت، وظیفه و حافظه
        assert [note.title for note in window.chat_store.list_notes()] == ["یادداشت پشتیبان"]
        assert window.notes_page._rows
        assert window.tasks_page._rows
        assert window.memory_page._rows
        assert window.chat_page.memory_label.isVisibleTo(window.chat_page) is True
    finally:
        window.close()
        window.deleteLater()


def _settings(tmp_path):
    """تنظیمات موقت برای صفحه تنظیمات."""
    from app.services.settings import AppSettings

    return AppSettings(tmp_path / ".env")
