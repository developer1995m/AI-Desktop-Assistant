"""محاسبه وضعیت موعد وظیفه‌ها و یافتن یادآوری‌های سررسیده.

منطق تاریخ عمداً از لایه ذخیره‌سازی جدا است تا هم پایگاه‌داده ساده بماند و هم
بتوان «امروز» را در تست‌ها تزریق کرد.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date

from app.services.storage import Task

OVERDUE = "overdue"
TODAY = "today"
SOON = "soon"
LATER = "later"
NONE = "none"

# موعدهایی که تا این تعداد روز آینده هستند «نزدیک» شمرده می‌شوند.
SOON_DAYS = 3

DUE_STATE_LABELS = {
    OVERDUE: "موعدش گذشته",
    TODAY: "امروز",
    SOON: "نزدیک",
    LATER: "بعدتر",
    NONE: "",
}


def parse_due_date(value: str) -> date | None:
    """موعد ذخیره‌شده را به تاریخ تبدیل می‌کند؛ خالی یا نامعتبر یعنی بدون موعد."""
    text = (value or "").strip()

    if not text:
        return None

    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def due_state(due_date: str, today: date | None = None) -> str:
    """وضعیت موعد را برمی‌گرداند: گذشته، امروز، نزدیک، بعدتر یا بدون موعد."""
    due = parse_due_date(due_date)

    if due is None:
        return NONE

    delta = (due - (today or date.today())).days

    if delta < 0:
        return OVERDUE

    if delta == 0:
        return TODAY

    if delta <= SOON_DAYS:
        return SOON

    return LATER


def due_label(due_date: str, today: date | None = None) -> str:
    """برچسب کوتاه فارسی موعد: امروز، فردا، ۳ روز دیگر، ۲ روز گذشته."""
    due = parse_due_date(due_date)

    if due is None:
        return ""

    delta = (due - (today or date.today())).days

    if delta == 0:
        return "امروز"

    if delta == 1:
        return "فردا"

    if delta == -1:
        return "دیروز"

    if delta < 0:
        return f"{-delta} روز گذشته"

    return f"{delta} روز دیگر"


def pending_reminders(tasks: Iterable[Task], today: date | None = None) -> list[Task]:
    """وظیفه‌های انجام‌نشده‌ای که موعدشان امروز است یا گذشته است."""
    reference = today or date.today()

    return [
        task
        for task in tasks
        if not task.done and due_state(task.due_date, reference) in {OVERDUE, TODAY}
    ]


def reminder_summary(tasks: Iterable[Task], today: date | None = None) -> str:
    """جمله یادآوری را می‌سازد؛ بدون موردی برای یادآوری، رشته خالی.

    مثال: «۲ وظیفه موعدش گذشته و ۱ وظیفه امروز موعد دارد.»
    """
    reference = today or date.today()
    overdue = 0
    due_today = 0

    for task in tasks:
        if task.done:
            continue

        state = due_state(task.due_date, reference)

        if state == OVERDUE:
            overdue += 1
        elif state == TODAY:
            due_today += 1

    parts: list[str] = []

    if overdue:
        parts.append(f"{overdue} وظیفه موعدش گذشته")

    if due_today:
        parts.append(f"{due_today} وظیفه امروز موعد دارد")

    if not parts:
        return ""

    return " و ".join(parts) + "."
