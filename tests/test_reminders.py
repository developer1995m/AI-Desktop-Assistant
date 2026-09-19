"""تست‌های منطق موعد وظیفه‌ها و یادآوری‌ها."""

from datetime import date

import pytest

from app.services import reminders
from app.services.reminders import (
    LATER,
    NONE,
    OVERDUE,
    SOON,
    TODAY,
    due_label,
    due_state,
    parse_due_date,
    pending_reminders,
    reminder_summary,
)
from app.services.storage import Task

TODAY_DATE = date(2026, 9, 18)


def make_task(due_date: str = "", *, done: bool = False, task_id: int = 1) -> Task:
    """یک وظیفه برای تست می‌سازد (بدون پایگاه‌داده)."""
    return Task(
        id=task_id,
        title="وظیفه",
        done=done,
        priority="normal",
        created_at="2026-09-01T00:00:00+00:00",
        updated_at="2026-09-01T00:00:00+00:00",
        due_date=due_date,
    )


def test_parse_due_date_accepts_iso_and_rejects_the_rest():
    assert parse_due_date("2026-09-18") == date(2026, 9, 18)
    assert parse_due_date("  2026-09-18  ") == date(2026, 9, 18)
    assert parse_due_date("") is None
    assert parse_due_date("18/09/2026") is None
    assert parse_due_date("فردا") is None


@pytest.mark.parametrize(
    ("due", "expected"),
    [
        ("", NONE),
        ("2026-09-15", OVERDUE),
        ("2026-09-17", OVERDUE),
        ("2026-09-18", TODAY),
        ("2026-09-19", SOON),
        ("2026-09-21", SOON),
        ("2026-09-22", LATER),
        ("2027-01-01", LATER),
    ],
)
def test_due_states_are_computed_against_a_given_day(due, expected):
    assert due_state(due, TODAY_DATE) == expected


@pytest.mark.parametrize(
    ("due", "expected"),
    [
        ("2026-09-18", "امروز"),
        ("2026-09-19", "فردا"),
        ("2026-09-17", "دیروز"),
        ("2026-09-15", "3 روز گذشته"),
        ("2026-09-21", "3 روز دیگر"),
    ],
)
def test_due_labels_read_naturally(due, expected):
    assert due_label(due, TODAY_DATE) == expected


def test_due_label_is_empty_without_a_date():
    assert due_label("", TODAY_DATE) == ""


def test_pending_reminders_ignore_done_and_future_tasks():
    tasks = [
        make_task("2026-09-15", task_id=1),
        make_task("2026-09-18", task_id=2),
        make_task("2026-09-19", task_id=3),
        make_task("", task_id=4),
        make_task("2026-09-10", done=True, task_id=5),
    ]

    pending = pending_reminders(tasks, TODAY_DATE)

    assert [task.id for task in pending] == [1, 2]


def test_summary_counts_overdue_and_today_separately():
    tasks = [
        make_task("2026-09-10", task_id=1),
        make_task("2026-09-17", task_id=2),
        make_task("2026-09-18", task_id=3),
        make_task("2026-09-19", task_id=4),
    ]

    assert reminder_summary(tasks, TODAY_DATE) == "2 وظیفه موعدش گذشته و 1 وظیفه امروز موعد دارد."


def test_summary_only_mentions_what_exists():
    assert reminder_summary([make_task("2026-09-18")], TODAY_DATE) == "1 وظیفه امروز موعد دارد."
    assert reminder_summary([make_task("2026-09-16")], TODAY_DATE) == "1 وظیفه موعدش گذشته."


def test_summary_is_empty_when_nothing_is_due():
    tasks = [make_task(""), make_task("2026-10-01"), make_task("2026-09-01", done=True)]

    assert reminder_summary(tasks, TODAY_DATE) == ""


def test_state_labels_cover_every_state():
    assert set(reminders.DUE_STATE_LABELS) == {OVERDUE, TODAY, SOON, LATER, NONE}
