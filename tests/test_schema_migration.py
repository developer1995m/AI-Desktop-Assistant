"""تست‌های ستون‌های تازه یادداشت و وظیفه و مهاجرت پایگاه‌داده‌های قدیمی."""

import sqlite3

import pytest

from app.services.storage import (
    MAX_NOTE_TAGS,
    MAX_TAG_CHARS,
    ConversationStore,
    normalise_due_date,
    normalise_tags,
    parse_tags,
)

OLD_SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    done INTEGER NOT NULL DEFAULT 0,
    priority TEXT NOT NULL DEFAULT 'normal',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


def make_old_database(path):
    """یک پایگاه‌داده با ساختار نسخه قبلی (بدون tags و due_date) می‌سازد."""
    connection = sqlite3.connect(path)
    connection.executescript(OLD_SCHEMA)
    connection.execute(
        "INSERT INTO notes (title, content, created_at, updated_at) VALUES (?, ?, ?, ?)",
        ("یادداشت قدیمی", "متن قدیمی", "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"),
    )
    connection.execute(
        "INSERT INTO tasks (title, done, priority, created_at, updated_at) "
        "VALUES (?, 0, 'high', ?, ?)",
        ("وظیفه قدیمی", "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"),
    )
    connection.commit()
    connection.close()


def test_old_database_is_migrated_without_losing_data(tmp_path):
    path = tmp_path / "old.db"
    make_old_database(path)

    store = ConversationStore(path)

    columns_notes = store._table_columns("notes")
    columns_tasks = store._table_columns("tasks")
    assert "tags" in columns_notes
    assert "due_date" in columns_tasks

    note = store.list_notes()[0]
    assert (note.title, note.content) == ("یادداشت قدیمی", "متن قدیمی")
    assert note.tags == ()

    task = store.list_tasks()[0]
    assert task.title == "وظیفه قدیمی"
    assert task.due_date == ""


def test_migration_is_idempotent(tmp_path):
    path = tmp_path / "old.db"
    make_old_database(path)

    ConversationStore(path).close()
    store = ConversationStore(path)

    assert store.count_notes() == 1
    assert store.count_tasks() == 1


def test_old_backup_restores_into_the_new_schema(tmp_path):
    # پشتیبان نسخه قبلی ستون‌های تازه را ندارد؛ بازیابی باید بدون خطا انجام شود.
    store = ConversationStore(tmp_path / "new.db")

    counts = store.restore(
        {
            "notes": [
                {
                    "id": 1,
                    "title": "از پشتیبان",
                    "content": "متن",
                    "created_at": "2026-01-01T00:00:00+00:00",
                    "updated_at": "2026-01-01T00:00:00+00:00",
                }
            ],
            "tasks": [
                {
                    "id": 1,
                    "title": "وظیفه از پشتیبان",
                    "done": 0,
                    "priority": "normal",
                    "created_at": "2026-01-01T00:00:00+00:00",
                    "updated_at": "2026-01-01T00:00:00+00:00",
                }
            ],
        }
    )

    assert counts["notes"] == 1
    assert counts["tasks"] == 1
    assert store.list_notes()[0].tags == ()
    assert store.list_tasks()[0].due_date == ""


# ------------------------------------------------------------------ برچسب‌ها


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("خرید، خانه", ("خرید", "خانه")),
        ("خرید, خانه ,  کار", ("خرید", "خانه", "کار")),
        ("", ()),
        ("  ", ()),
        ("،،", ()),
        ("خرید, خرید, خرید", ("خرید",)),
        ("خرید, خرید ", ("خرید",)),
        ("Python, python", ("Python",)),
        ("چند   فاصله", ("چند فاصله",)),
    ],
)
def test_parse_tags_normalises_input(text, expected):
    assert parse_tags(text) == expected


def test_parse_tags_limits_count_and_length():
    many = ", ".join(f"برچسب{index}" for index in range(MAX_NOTE_TAGS + 5))

    assert len(parse_tags(many)) == MAX_NOTE_TAGS
    assert len(parse_tags("x" * 100)[0]) == MAX_TAG_CHARS


def test_normalise_tags_is_stable():
    once = normalise_tags(" خرید ، کار,خرید ")
    twice = normalise_tags(once)

    assert once == "خرید, کار"
    assert twice == once


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2026-09-18", "2026-09-18"),
        (" 2026-09-18 ", "2026-09-18"),
        ("2026-01-05", "2026-01-05"),
        ("", ""),
        ("   ", ""),
    ],
)
def test_normalise_due_date_normalises_iso_dates(value, expected):
    assert normalise_due_date(value) == expected


@pytest.mark.parametrize("value", ["18/09/2026", "فردا", "2026-13-40", "2026-02-30"])
def test_normalise_due_date_rejects_nonsense(value):
    with pytest.raises(ValueError):
        normalise_due_date(value)


def test_notes_keep_tags_and_expose_them_as_a_tuple(tmp_path):
    store = ConversationStore(tmp_path / "chat.db")

    note_id = store.create_note("لیست", "نان و پنیر", tags=" خرید ، خانه,خرید ")
    note = store.get_note(note_id)

    assert note.tags == ("خرید", "خانه")

    store.update_note(note_id, "لیست", "نان و پنیر و چای", tags="خانه")
    assert store.get_note(note_id).tags == ("خانه",)

    store.update_note(note_id, "لیست", "نان")
    assert store.get_note(note_id).tags == ()


def test_list_note_tags_counts_notes(tmp_path):
    store = ConversationStore(tmp_path / "chat.db")
    store.create_note("یک", "الف", tags="کار, خانه")
    store.create_note("دو", "ب", tags="خانه")
    store.create_note("سه", "ج")

    # پربسامدترین برچسب اول می‌آید.
    assert store.list_note_tags() == [("خانه", 2), ("کار", 1)]


def test_tasks_keep_due_dates_and_sort_by_the_nearest(tmp_path):
    store = ConversationStore(tmp_path / "chat.db")

    later = store.create_task("بعدتر", "high", due_date="2026-12-01")
    soon = store.create_task("زودتر", "low", due_date="2026-09-20")
    without = store.create_task("بدون موعد", "high")

    assert [task.id for task in store.list_tasks()] == [soon, later, without]
    assert store.get_task(soon).due_date == "2026-09-20"

    store.set_task_due_date(later, "")
    assert store.get_task(later).due_date == ""


def test_task_with_invalid_due_date_is_rejected(tmp_path):
    store = ConversationStore(tmp_path / "chat.db")

    with pytest.raises(ValueError):
        store.create_task("وظیفه", "normal", due_date="فردا")


def test_done_tasks_never_sort_above_open_ones(tmp_path):
    store = ConversationStore(tmp_path / "chat.db")
    store.create_task("انجام‌شده", "high", due_date="2026-09-01")
    open_task = store.create_task("باز", "low")
    done_id = store.list_tasks()[0].id

    # وظیفه دارای موعد را انجام‌شده می‌کنیم؛ دیگر نباید بالای کارهای باز بیاید.
    store.set_task_done(done_id, True)

    assert store.list_tasks()[0].id == open_task
