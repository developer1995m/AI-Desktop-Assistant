"""صفحه وظایف."""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence

from PySide6.QtCore import QDate, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.services.reminders import OVERDUE, TODAY, due_label, due_state
from app.services.storage import (
    TASK_PRIORITIES,
    TASK_PRIORITY_LABELS,
    ConversationStore,
    Task,
)

# همان نگاشت مشترک؛ جست‌وجوی سراسری هم از همین برچسب‌ها استفاده می‌کند.
PRIORITY_LABELS = TASK_PRIORITY_LABELS


def priority_label(priority: str) -> str:
    """برچسب نمایشی اولویت را برمی‌گرداند."""
    return PRIORITY_LABELS.get(priority, priority)


class DueDateDialog(QDialog):
    """انتخاب یا پاک‌کردن موعد یک وظیفه.

    مقدار `""` یعنی «بدون موعد»؛ همین مقدار وقتی صدا زده می‌شود که کاربر موعد را
    پاک کرده باشد.
    """

    def __init__(self, due_date: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self.setWindowTitle("موعد وظیفه")
        self.setObjectName("dueDateDialog")
        self.setMinimumWidth(280)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)

        hint = QLabel("تاریخ موعد را انتخاب کنید؛ با «بدون موعد» پاک می‌شود.")
        hint.setObjectName("pageDescription")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.date_input = QDateEdit()
        self.date_input.setObjectName("taskDueInput")
        self.date_input.setCalendarPopup(True)
        self.date_input.setDisplayFormat("yyyy-MM-dd")
        self.date_input.setDate(self._to_qdate(due_date) or QDate.currentDate())
        layout.addWidget(self.date_input)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)

        self.clear_button = self.buttons.addButton(
            "بدون موعد", QDialogButtonBox.ButtonRole.ResetRole
        )
        self.clear_button.setObjectName("ghostButton")
        self.clear_button.clicked.connect(self._clear)

        layout.addWidget(self.buttons)

    @staticmethod
    def _to_qdate(due_date: str) -> QDate | None:
        """تاریخ ISO را به QDate تبدیل می‌کند؛ مقدار خالی یا نامعتبر None است."""
        parsed = QDate.fromString((due_date or "").strip(), Qt.DateFormat.ISODate)

        return parsed if parsed.isValid() else None

    def _clear(self) -> None:
        """بدون موعد: مقدار خالی ثبت و دیالوگ بسته می‌شود."""
        self.date_input.setDate(QDate.fromString("2000-01-01", Qt.DateFormat.ISODate))
        self.accept()

    def value(self) -> str:
        """موعد انتخاب‌شده به شکل ISO؛ خالی یعنی بدون موعد."""
        date = self.date_input.date()

        if date == QDate.fromString("2000-01-01", Qt.DateFormat.ISODate):
            return ""

        return date.toString("yyyy-MM-dd")


class TasksPage(QWidget):
    """ایجاد وظیفه، تیک‌زدن انجام‌شده‌ها و حذف."""

    tasks_changed = Signal()

    def __init__(self, store: ConversationStore, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self.setObjectName("tasksPage")

        self._store = store
        self._rows: list[QWidget] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 24, 32, 24)
        layout.setSpacing(16)

        layout.addWidget(self._create_heading())
        layout.addWidget(self._create_composer())
        layout.addWidget(self._create_filter_bar())

        self.list_frame = self._create_list_frame()
        layout.addWidget(self.list_frame, 1)

        self.refresh()

    # ------------------------------------------------------------------ ساخت رابط

    def _create_heading(self) -> QWidget:
        """سربرگ صفحه وظایف."""
        heading = QWidget()

        layout = QVBoxLayout(heading)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        title_label = QLabel("وظایف")
        title_label.setObjectName("pageTitle")
        layout.addWidget(title_label)

        return heading

    def _create_composer(self) -> QFrame:
        """کادر افزودن وظیفه جدید."""
        frame = QFrame()
        frame.setObjectName("taskComposer")

        outer_layout = QVBoxLayout(frame)
        outer_layout.setContentsMargins(16, 12, 16, 12)
        outer_layout.setSpacing(8)

        first_row = QWidget()
        layout = QHBoxLayout(first_row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        self.title_input = QLineEdit()
        self.title_input.setObjectName("taskTitleInput")
        self.title_input.setPlaceholderText("وظیفه جدید… (Enter برای افزودن)")
        self.title_input.returnPressed.connect(self._create_from_composer)
        layout.addWidget(self.title_input, 1)

        self.priority_combo = QComboBox()
        self.priority_combo.setObjectName("taskPriorityCombo")
        for priority in TASK_PRIORITIES:
            self.priority_combo.addItem(priority_label(priority), priority)
        self.priority_combo.setCurrentIndex(1)  # معمولی
        layout.addWidget(self.priority_combo)

        self.add_button = QPushButton("افزودن")
        self.add_button.setObjectName("primaryButton")
        self.add_button.setFixedHeight(34)
        self.add_button.clicked.connect(self._create_from_composer)
        layout.addWidget(self.add_button)

        outer_layout.addWidget(first_row)

        second_row = QWidget()
        due_layout = QHBoxLayout(second_row)
        due_layout.setContentsMargins(0, 0, 0, 0)
        due_layout.setSpacing(8)

        self.due_checkbox = QCheckBox("موعد دارد")
        self.due_checkbox.setObjectName("taskDueCheck")
        self.due_checkbox.toggled.connect(self._on_due_toggled)

        self.due_input = QDateEdit()
        self.due_input.setObjectName("taskDueInput")
        self.due_input.setCalendarPopup(True)
        self.due_input.setDisplayFormat("yyyy-MM-dd")
        self.due_input.setDate(QDate.currentDate())
        self.due_input.setEnabled(False)

        due_layout.addWidget(self.due_checkbox)
        due_layout.addWidget(self.due_input)
        due_layout.addStretch(1)

        outer_layout.addWidget(second_row)

        return frame

    def _on_due_toggled(self, checked: bool) -> None:
        """ورودی تاریخ فقط زمانی فعال است که وظیفه موعد داشته باشد."""
        self.due_input.setEnabled(checked)

        if checked:
            # موعد در گذشته برای وظیفه تازه معنا ندارد.
            if self.due_input.date() < QDate.currentDate():
                self.due_input.setDate(QDate.currentDate())

    def due_date_value(self) -> str:
        """موعد انتخاب‌شده در کادر افزودن؛ خالی یعنی بدون موعد."""
        if not self.due_checkbox.isChecked():
            return ""

        return self.due_input.date().toString("yyyy-MM-dd")

    def _create_filter_bar(self) -> QWidget:
        """نوار فیلتر وضعیت و شمارنده‌ها."""
        bar = QWidget()

        layout = QHBoxLayout(bar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        self.filter_combo = QComboBox()
        self.filter_combo.setObjectName("taskFilterCombo")
        self.filter_combo.addItem("همه", "all")
        self.filter_combo.addItem("انجام‌نشده", "open")
        self.filter_combo.addItem("موعدش گذشته", "overdue")
        self.filter_combo.addItem("امروز موعد دارد", "today")
        self.filter_combo.addItem("انجام‌شده", "done")
        self.filter_combo.currentIndexChanged.connect(lambda _index: self.refresh())
        layout.addWidget(self.filter_combo)

        layout.addStretch(1)

        self.counter_label = QLabel()
        self.counter_label.setObjectName("taskCounter")
        layout.addWidget(self.counter_label)

        return bar

    def _create_list_frame(self) -> QFrame:
        """کادر فهرست وظایف."""
        frame = QFrame()
        frame.setObjectName("taskListFrame")

        frame_layout = QVBoxLayout(frame)
        frame_layout.setContentsMargins(16, 12, 16, 12)
        frame_layout.setSpacing(8)

        self.empty_label = QLabel("وظیفه‌ای ندارید؛ یکی اضافه کنید.")
        self.empty_label.setObjectName("tasksEmpty")
        self.empty_label.setWordWrap(True)
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        frame_layout.addWidget(self.empty_label)

        self._container = QWidget()
        self._container.setObjectName("tasksContainer")

        self._list_layout = QVBoxLayout(self._container)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(6)
        self._list_layout.addStretch(1)

        scroll_area = QScrollArea()
        scroll_area.setObjectName("tasksScroll")
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_area.setWidget(self._container)

        frame_layout.addWidget(scroll_area, 1)

        return frame

    # --------------------------------------------------------------------- رفتار

    def refresh(self) -> None:
        """فهرست وظایف و شمارنده‌ها را از پایگاه‌داده تازه می‌کند."""
        filter_mode = self.filter_combo.currentData() or "all"

        try:
            if filter_mode == "open":
                tasks = self._store.list_tasks(include_done=False)
            elif filter_mode == "overdue":
                tasks = [
                    task
                    for task in self._store.list_tasks(include_done=False)
                    if due_state(task.due_date) == OVERDUE
                ]
            elif filter_mode == "today":
                tasks = [
                    task
                    for task in self._store.list_tasks(include_done=False)
                    if due_state(task.due_date) == TODAY
                ]
            elif filter_mode == "done":
                tasks = [task for task in self._store.list_tasks() if task.done]
            else:
                tasks = self._store.list_tasks()

            open_count = self._store.count_tasks(include_done=False)
            total_count = self._store.count_tasks()
        except sqlite3.Error as error:
            self.empty_label.setText(f"خواندن وظایف ناموفق بود: {error}")
            tasks = []
            open_count = total_count = 0

        self.counter_label.setText(f"{open_count} انجام‌نشده از {total_count} وظیفه")
        self._fill_rows(tasks)

    def _fill_rows(self, tasks: Sequence[Task]) -> None:
        """ردیف‌های وظایف را از نو می‌سازد."""
        self._clear_rows()

        for task in tasks:
            row = self._create_row(task)
            self._list_layout.insertWidget(self._list_layout.count() - 1, row)
            self._rows.append(row)

        has_rows = bool(self._rows)
        self._container.setVisible(has_rows)
        self.empty_label.setVisible(not has_rows)
        self.empty_label.setText(
            "وظیفه‌ای با این فیلتر نیست."
            if self.filter_combo.currentData() in {"overdue", "today"}
            else "وظیفه‌ای ندارید؛ یکی اضافه کنید."
        )

    def _clear_rows(self) -> None:
        """ردیف‌های فعلی را از رابط کاربری حذف می‌کند."""
        for row in self._rows:
            self._list_layout.removeWidget(row)
            row.setParent(None)
            row.deleteLater()

        self._rows.clear()

    def _create_row(self, task: Task) -> QWidget:
        """یک ردیف وظیفه با چک‌باکس، اولویت و دکمه حذف می‌سازد."""
        row = QWidget()
        row.setObjectName("taskRowDone" if task.done else "taskRow")

        layout = QHBoxLayout(row)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(10)

        checkbox = QCheckBox()
        checkbox.setObjectName("taskCheckbox")
        checkbox.setChecked(task.done)
        checkbox.toggled.connect(
            lambda checked, task_id=task.id: self._toggle_task(task_id, checked)
        )
        layout.addWidget(checkbox)

        title_label = QLabel(task.title)
        title_label.setObjectName("taskTitle")
        title_label.setToolTip(task.title)
        if task.done:
            title_label.setStyleSheet("text-decoration: line-through;")
        layout.addWidget(title_label, 1)

        if task.due_date:
            state = due_state(task.due_date)
            due_chip = QLabel(f"{due_label(task.due_date)}")
            due_chip.setObjectName(f"dueChip{state.capitalize()}")
            due_chip.setToolTip(f"موعد: {task.due_date}")
            layout.addWidget(due_chip)

        priority_chip = QLabel(priority_label(task.priority))
        priority_chip.setObjectName(f"priorityChip{task.priority.capitalize()}")
        layout.addWidget(priority_chip)

        due_button = QPushButton("موعد")
        due_button.setObjectName("ghostButton")
        due_button.setFixedHeight(28)
        due_button.setToolTip("تعیین یا پاک‌کردن موعد")
        due_button.clicked.connect(
            lambda checked=False, task_id=task.id: self._edit_due_date(task_id)
        )
        layout.addWidget(due_button)

        delete_button = QPushButton("حذف")
        delete_button.setObjectName("dangerButton")
        delete_button.setFixedHeight(28)
        delete_button.clicked.connect(
            lambda checked=False, task_id=task.id: self._delete_task(task_id)
        )
        layout.addWidget(delete_button)

        return row

    def _create_from_composer(self) -> None:
        """وظیفه‌ای از کادر افزودن می‌سازد."""
        title = self.title_input.text().strip()
        if not title:
            return

        priority = self.priority_combo.currentData() or "normal"

        try:
            self._store.create_task(title, priority, due_date=self.due_date_value())
        except (sqlite3.Error, ValueError) as error:
            self.empty_label.setText(f"افزودن وظیفه ناموفق بود: {error}")
            self.empty_label.setVisible(True)
            return

        self.title_input.clear()
        self.due_checkbox.setChecked(False)
        self.title_input.setFocus()
        self.tasks_changed.emit()
        self.refresh()

    # -------------------------------------------------------------------- موعد

    def _edit_due_date(self, task_id: int) -> None:
        """موعد وظیفه را با یک دیالوگ کوچک تعیین یا پاک می‌کند."""
        try:
            task = self._store.get_task(task_id)
        except sqlite3.Error as error:
            self.empty_label.setText(f"خواندن وظیفه ناموفق بود: {error}")
            self.empty_label.setVisible(True)
            return

        if task is None:
            return

        dialog = DueDateDialog(task.due_date, self)
        self.due_dialog = dialog

        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.set_due_date(task_id, dialog.value())

    def set_due_date(self, task_id: int, due_date: str) -> bool:
        """موعد یک وظیفه را ثبت می‌کند و فهرست را تازه می‌کند."""
        try:
            self._store.set_task_due_date(task_id, due_date)
        except (sqlite3.Error, ValueError) as error:
            self.empty_label.setText(f"ثبت موعد ناموفق بود: {error}")
            self.empty_label.setVisible(True)
            return False

        self.tasks_changed.emit()
        self.refresh()

        return True

    def _toggle_task(self, task_id: int, done: bool) -> None:
        """وضعیت انجام وظیفه را عوض می‌کند."""
        try:
            self._store.set_task_done(task_id, done)
        except sqlite3.Error as error:
            self.empty_label.setText(f"به‌روزرسانی وظیفه ناموفق بود: {error}")
            self.empty_label.setVisible(True)
            return

        self.tasks_changed.emit()
        self.refresh()

    def _delete_task(self, task_id: int) -> None:
        """پس از تأیید، وظیفه را حذف می‌کند."""
        answer = QMessageBox.question(
            self,
            "حذف وظیفه",
            "این وظیفه برای همیشه حذف شود؟",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if answer != QMessageBox.StandardButton.Yes:
            return

        try:
            self._store.delete_task(task_id)
        except sqlite3.Error as error:
            self.empty_label.setText(f"حذف وظیفه ناموفق بود: {error}")
            self.empty_label.setVisible(True)
            return

        self.tasks_changed.emit()
        self.refresh()
