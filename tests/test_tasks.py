"""تست‌های ذخیره‌سازی وظایف و صفحه Tasks."""

from datetime import date, timedelta

import pytest
from PySide6.QtWidgets import QDialog, QLabel, QMessageBox, QPushButton

from app.services.reminders import OVERDUE, TODAY
from app.services.storage import ConversationStore
from app.ui.main_window import MainWindow
from app.ui.pages.tasks_page import DueDateDialog, TasksPage, priority_label

from tests.test_main_window import make_window


def days_from_today(offset: int) -> str:
    """تاریخ نسبی به شکل YYYY-MM-DD.

    تست‌ها نباید تاریخ مطلق بنویسند؛ وگرنه فردای همان روز شروع به شکستن می‌کنند
    (وظیفه «امروزی» ناگهان سررسیده می‌شود).
    """
    return (date.today() + timedelta(days=offset)).isoformat()


def make_tasks_page(tmp_path):
    store = ConversationStore(tmp_path / "chat.db")
    return store, TasksPage(store)


def task_row_buttons(page, row_index: int, label: str) -> list[QPushButton]:
    """دکمه‌های یک لیبل مشخص در ردیف وظیفه را برمی‌گرداند."""
    row = page._rows[row_index]

    return [button for button in row.findChildren(QPushButton) if button.text() == label]


def row_title(page, row_index: int) -> str:
    """عنوان وظیفه در ردیف داده‌شده (برای یافتن ردیف یک وظیفه خاص)."""
    row = page._rows[row_index]

    for label in row.findChildren(QLabel):
        if label.objectName() == "taskTitle":
            return label.text()

    return ""


def due_chip_text(page, title: str) -> str:
    """متن چیپ موعد وظیفه با عنوان داده‌شده؛ بدون موعد رشته خالی."""
    for row in page._rows:
        if row_title_of(row) == title:
            for label in row.findChildren(QLabel):
                if label.objectName().startswith("dueChip"):
                    return label.text()

    return ""


def row_title_of(row) -> str:
    for label in row.findChildren(QLabel):
        if label.objectName() == "taskTitle":
            return label.text()

    return ""


def test_task_crud_round_trip(tmp_path):
    store = ConversationStore(tmp_path / "chat.db")

    task_id = store.create_task("خرید نان", "high")
    task = store.get_task(task_id)
    assert task.title == "خرید نان"
    assert task.done is False
    assert task.priority == "high"

    store.update_task(task_id, "خرید نان و شیر", "low")
    updated = store.get_task(task_id)
    assert updated.title == "خرید نان و شیر"
    assert updated.priority == "low"

    store.set_task_done(task_id, True)
    assert store.get_task(task_id).done is True
    assert store.count_tasks(include_done=False) == 0
    assert store.count_tasks() == 1

    store.delete_task(task_id)
    assert store.count_tasks() == 0
    assert store.get_task(task_id) is None


def test_create_task_rejects_bad_priority(tmp_path):
    store = ConversationStore(tmp_path / "chat.db")

    with pytest.raises(ValueError):
        store.create_task("وظیفه", "urgent")

    with pytest.raises(ValueError):
        store.update_task(store.create_task("وظیفه"), "وظیفه", "urgent")


def test_list_tasks_orders_open_before_done_and_by_priority(tmp_path):
    store = ConversationStore(tmp_path / "chat.db")
    low = store.create_task("کم", "low")
    high = store.create_task("مهم", "high")
    normal = store.create_task("معمولی", "normal")

    # همه باز هستند: ترتیب اولویت مهم → معمولی → کم
    assert [task.id for task in store.list_tasks()] == [high, normal, low]
    assert [task.id for task in store.list_tasks(include_done=False)] == [
        high,
        normal,
        low,
    ]

    store.set_task_done(low, True)

    ids = [task.id for task in store.list_tasks()]
    assert ids == [high, normal, low]  # انجام‌شده به ته فهرست میرود

    assert [task.id for task in store.list_tasks(include_done=False)] == [high, normal]
    done_only = [task.id for task in store.list_tasks() if task.done]
    assert done_only == [low]


def test_priority_label_known_values():
    assert priority_label("high") == "مهم"
    assert priority_label("normal") == "معمولی"
    assert priority_label("low") == "کم"
    assert priority_label("anything") == "anything"


def test_tasks_page_starts_empty(qt_app, tmp_path):
    store, page = make_tasks_page(tmp_path)
    page.show()

    assert page._rows == []
    assert page.empty_label.isVisible() is True
    assert "0" in page.counter_label.text()


def test_create_task_from_composer(qt_app, tmp_path):
    store, page = make_tasks_page(tmp_path)
    page.show()

    page.title_input.setText("وظیفه از رابط")
    # ترتیب آیتم‌ها همان TASK_PRIORITIES است: low، normal، high
    page.priority_combo.setCurrentIndex(2)  # مهم
    page.add_button.click()

    tasks = store.list_tasks()
    assert len(tasks) == 1
    assert tasks[0].priority == "high"
    assert page.title_input.text() == ""
    assert len(page._rows) == 1


def test_composer_rejects_empty_title(qt_app, tmp_path):
    store, page = make_tasks_page(tmp_path)
    page.show()

    page.add_button.click()

    assert store.count_tasks() == 0
    assert len(page._rows) == 0


def test_toggle_done_moves_task(qt_app, tmp_path):
    from PySide6.QtWidgets import QCheckBox

    store, page = make_tasks_page(tmp_path)
    task_id = store.create_task("تیک‌شدنی")
    page.refresh()
    page.show()

    checkbox = page._rows[0].findChild(QCheckBox)
    assert checkbox.isChecked() is False

    checkbox.setChecked(True)

    assert store.get_task(task_id).done is True
    # با فیلتر «همه»، وظیفه انجام‌شده به ته فهرست میرود.
    assert page._rows[0].objectName() == "taskRowDone"


def test_filter_combo_shows_subset(qt_app, tmp_path):
    store, page = make_tasks_page(tmp_path)
    done_id = store.create_task("انجام‌شده")
    store.set_task_done(done_id, True)
    store.create_task("باز")
    page.show()
    page.filter_combo.setCurrentIndex(page.filter_combo.findData("open"))
    assert len(page._rows) == 1

    page.filter_combo.setCurrentIndex(page.filter_combo.findData("done"))
    assert len(page._rows) == 1

    page.filter_combo.setCurrentIndex(0)  # همه
    assert len(page._rows) == 2


def test_delete_task_with_confirmation(qt_app, tmp_path, monkeypatch):
    store, page = make_tasks_page(tmp_path)
    task_id = store.create_task("حذف‌شدنی")
    page.refresh()
    page.show()

    monkeypatch.setattr(
        QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.No
    )
    task_row_buttons(page, 0, "حذف")[0].click()
    assert store.count_tasks() == 1

    monkeypatch.setattr(
        QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Yes
    )
    task_row_buttons(page, 0, "حذف")[0].click()

    assert store.count_tasks() == 0
    assert page._rows == []
    assert page.empty_label.isVisible() is True


def test_main_window_tasks_page_syncs_dashboard(qt_app, tmp_path, monkeypatch):
    window = make_window(qt_app, tmp_path, monkeypatch)
    window.show()
    window.show_page("tasks")

    window.tasks_page.title_input.setText("از پنجره اصلی")
    window.tasks_page.add_button.click()

    assert window.chat_store.count_tasks() == 1
    assert len(window.tasks_page._rows) == 1

    window.close()


# ------------------------------------------------------------------------ موعد


def test_composer_creates_a_task_with_a_due_date(qt_app, tmp_path):
    store, page = make_tasks_page(tmp_path)

    page.due_checkbox.setChecked(True)
    page.title_input.setText("پرداخت قبض")
    page.add_button.click()

    task = store.list_tasks()[0]
    assert task.due_date != ""
    # پس از افزودن، کادر برای وظیفه بعدی خاموش می‌شود.
    assert page.due_checkbox.isChecked() is False


def test_due_chip_shows_a_short_label(qt_app, tmp_path):
    store, page = make_tasks_page(tmp_path)
    store.create_task("امروزی", "normal", due_date=days_from_today(0))
    store.create_task("گذشته", "normal", due_date=days_from_today(-8))
    store.create_task("بی‌موعد")
    page.refresh()

    assert due_chip_text(page, "امروزی") == "امروز"
    assert "گذشته" in due_chip_text(page, "گذشته")
    assert due_chip_text(page, "بی‌موعد") == ""


def test_due_chip_object_names_follow_the_state(qt_app, tmp_path):
    store, page = make_tasks_page(tmp_path)
    store.create_task("امروزی", "normal", due_date=days_from_today(0))
    page.refresh()

    chips = [
        label.objectName()
        for row in page._rows
        for label in row.findChildren(QLabel)
        if label.objectName().startswith("dueChip")
    ]

    assert chips == ["dueChipToday"]


def test_set_due_date_updates_and_refreshes(qt_app, tmp_path):
    store, page = make_tasks_page(tmp_path)
    task_id = store.create_task("وظیفه")

    assert page.set_due_date(task_id, "2026-09-18") is True
    assert store.get_task(task_id).due_date == "2026-09-18"

    # پاک‌کردن موعد هم باید درست کار کند.
    assert page.set_due_date(task_id, "") is True
    assert store.get_task(task_id).due_date == ""


def test_set_due_date_rejects_a_nonsense_date(qt_app, tmp_path):
    store, page = make_tasks_page(tmp_path)
    task_id = store.create_task("وظیفه")

    assert page.set_due_date(task_id, "فردا") is False
    assert store.get_task(task_id).due_date == ""
    assert "ثبت موعد ناموفق بود" in page.empty_label.text()


def test_due_date_dialog_clears_to_empty(qt_app, tmp_path):
    dialog = DueDateDialog("2026-09-18")

    assert dialog.value() == "2026-09-18"

    dialog.clear_button.click()

    assert dialog.value() == ""


def test_due_date_dialog_shows_an_invalid_saved_value_as_today(qt_app, tmp_path):
    dialog = DueDateDialog("نه-تاریخ")

    # مقدار نامعتبر ذخیره‌شده به یک تاریخ معتبر برمی‌گردد تا دیالوگ قابل استفاده بماند.
    assert dialog.date_input.date().isValid() is True


def test_overdue_filter_shows_only_overdue(qt_app, tmp_path):
    store, page = make_tasks_page(tmp_path)
    store.create_task("گذشته", "normal", due_date=days_from_today(-10))
    store.create_task("امروزی", "normal", due_date=days_from_today(0))
    store.create_task("آینده", "normal", due_date=days_from_today(10))
    store.create_task("بی‌موعد")
    page.refresh()

    page.filter_combo.setCurrentIndex(page.filter_combo.findData("overdue"))

    assert [row_title(page, index) for index in range(len(page._rows))] == ["گذشته"]

    page.filter_combo.setCurrentIndex(page.filter_combo.findData("today"))
    assert [row_title(page, index) for index in range(len(page._rows))] == ["امروزی"]


def test_nearest_due_date_sorts_first_regardless_of_priority(qt_app, tmp_path):
    store, page = make_tasks_page(tmp_path)
    store.create_task("مهم ولی دور", "high")
    store.create_task("عادی ولی نزدیک", "normal", due_date=days_from_today(0))
    page.refresh()

    assert row_title(page, 0) == "عادی ولی نزدیک"


def test_main_window_shows_a_reminder_chip_for_due_tasks(qt_app, tmp_path, monkeypatch):
    store = ConversationStore(tmp_path / "chat.db")
    store.create_task("گذشته", "normal", due_date=days_from_today(-9))
    store.create_task("امروزی", "normal", due_date=days_from_today(0))
    store.create_task("آینده", "normal", due_date=days_from_today(10))

    window = make_window(qt_app, tmp_path, monkeypatch, store=store)
    window.show()

    # چیپ یادآوری سربرگ باید خلاصه وظایف سررسیده را نشان دهد (تاریخ امروز ثابت نیست،
    # پس فقط شمار کلی را می‌سنحیم).
    assert window.reminder_label.isVisibleTo(window) is True
    assert "1 وظیفه امروز موعد دارد" in window.reminder_label.text()

    # کلیک روی چیپ کاربر را به صفحه وظایف می‌برد.
    window.reminder_label.click()
    assert window.page_stack.currentWidget() is window.tasks_page

    window.close()


def test_reminder_chip_hides_when_nothing_is_due(qt_app, tmp_path, monkeypatch):
    store = ConversationStore(tmp_path / "chat.db")
    store.create_task("آینده", "normal", due_date=days_from_today(10))
    store.create_task("بی‌موعد")

    window = make_window(qt_app, tmp_path, monkeypatch, store=store)
    window.show()

    assert window.reminder_label.isVisibleTo(window) is False

    # بستن تنها وظیفه سررسیده هم چیپ را پنهان می‌کند.
    store.create_task("گذشته", "normal", due_date=days_from_today(-10))
    window.check_task_reminders()
    assert window.reminder_label.isVisibleTo(window) is True

    store.set_task_done(store.list_tasks()[0].id, True)
    window.check_task_reminders()
    assert window.reminder_label.isVisibleTo(window) is False

    window.close()


def test_check_task_reminders_emits_the_signal(qt_app, tmp_path, monkeypatch):
    store = ConversationStore(tmp_path / "chat.db")
    store.create_task("امروزی", "normal", due_date=days_from_today(0))

    window = make_window(qt_app, tmp_path, monkeypatch, store=store)
    received: list[str] = []
    window.reminder_triggered.connect(received.append)

    window.check_task_reminders(quiet=True)
    assert received == ["1 وظیفه امروز موعد دارد."]

    # در حالت بی‌صدا، بدون مورد سررسیده سیگنالی صادر نمی‌شود.
    received.clear()
    store.set_task_done(store.list_tasks()[0].id, True)
    window.check_task_reminders(quiet=True)
    assert received == []
    assert window.reminder_label.isVisibleTo(window) is False

    window.close()


def test_due_button_on_each_row_opens_the_dialog_and_saves(qt_app, tmp_path, monkeypatch):
    store, page = make_tasks_page(tmp_path)
    task_id = store.create_task("وظیفه")
    page.refresh()

    # دیالوگ موعد را ساختگی می‌کنیم تا بدون تعامل کاربر، نتیجه ثابت باشد.
    class FakeDialog:
        def __init__(self, value, parent=None):
            self.value_result = value

        def exec(self):
            return QDialog.DialogCode.Accepted

        def value(self):
            return "2026-09-18"

    monkeypatch.setattr("app.ui.pages.tasks_page.DueDateDialog", FakeDialog)
    task_row_buttons(page, 0, "موعد")[0].click()

    assert store.get_task(task_id).due_date == "2026-09-18"
