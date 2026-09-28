"""صفحه حافظه؛ واقعیت‌های ماندگار درباره کاربر."""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
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

from app.services.storage import ConversationStore, Memory

MAX_MEMORY_CHARS = 400


class MemoryPage(QWidget):
    """مدیریت واقعیت‌هایی که همیشه همراه پرامپت چت ارسال می‌شوند."""

    memories_changed = Signal()

    def __init__(self, store: ConversationStore, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self.setObjectName("memoryPage")

        self._store = store
        self._rows: list[QWidget] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 24, 32, 24)
        layout.setSpacing(16)

        layout.addWidget(self._create_heading())
        layout.addWidget(self._create_composer())
        layout.addWidget(self._create_list_frame(), 1)

        self.refresh()

    # ------------------------------------------------------------------ ساخت رابط

    def _create_heading(self) -> QWidget:
        """سربرگ صفحه حافظه."""
        heading = QWidget()

        layout = QVBoxLayout(heading)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        title_label = QLabel("حافظه")
        title_label.setObjectName("pageTitle")
        layout.addWidget(title_label)

        description_label = QLabel(
            "این واقعیت‌ها با هر پیام به مدل ارسال می‌شوند؛ فقط نکته‌های ماندگار را "
            "اینجا نگه دارید. حافظه غیرفعال‌شده ارسال نمیشود."
        )
        description_label.setObjectName("pageDescription")
        description_label.setWordWrap(True)
        layout.addWidget(description_label)

        return heading

    def _create_composer(self) -> QFrame:
        """کادر افزودن واقعیت جدید."""
        frame = QFrame()
        frame.setObjectName("memoryComposer")

        layout = QHBoxLayout(frame)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(10)

        self.content_input = QLineEdit()
        self.content_input.setObjectName("memoryInput")
        self.content_input.setPlaceholderText("مثلاً: نام من مسعود است و فارسی حرف می‌زنم")
        self.content_input.setMaxLength(MAX_MEMORY_CHARS)
        self.content_input.returnPressed.connect(self._add_from_composer)
        layout.addWidget(self.content_input, 1)

        self.add_button = QPushButton("افزودن")
        self.add_button.setObjectName("primaryButton")
        self.add_button.setFixedHeight(34)
        self.add_button.clicked.connect(self._add_from_composer)
        layout.addWidget(self.add_button)

        return frame

    def _create_list_frame(self) -> QFrame:
        """کادر فهرست حافظه‌ها."""
        frame = QFrame()
        frame.setObjectName("memoryListFrame")

        frame_layout = QVBoxLayout(frame)
        frame_layout.setContentsMargins(16, 12, 16, 12)
        frame_layout.setSpacing(8)

        self.counter_label = QLabel()
        self.counter_label.setObjectName("memoryCounter")
        frame_layout.addWidget(self.counter_label)

        self.empty_label = QLabel("هنوز چیزی در حافظه ذخیره نشده است.")
        self.empty_label.setObjectName("memoryEmpty")
        self.empty_label.setWordWrap(True)
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        frame_layout.addWidget(self.empty_label)

        self._container = QWidget()
        self._container.setObjectName("memoriesContainer")

        self._list_layout = QVBoxLayout(self._container)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(6)
        self._list_layout.addStretch(1)

        scroll_area = QScrollArea()
        scroll_area.setObjectName("memoriesScroll")
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_area.setWidget(self._container)

        frame_layout.addWidget(scroll_area, 1)

        return frame

    # --------------------------------------------------------------------- رفتار

    def refresh(self) -> None:
        """فهرست حافظه‌ها و شمارنده‌ها را از پایگاه‌داده تازه می‌کند."""
        try:
            memories = self._store.list_memories()
            active_count = self._store.count_memories(only_enabled=True)
        except sqlite3.Error as error:
            self.counter_label.setText(f"خواندن حافظه ناموفق بود: {error}")
            memories = []
            active_count = 0

        self.counter_label.setText(
            f"{active_count} فعال از {len(memories)} واقعیت"
        )
        self._fill_rows(memories)

    def _fill_rows(self, memories: Sequence[Memory]) -> None:
        """ردیف‌های حافظه را از نو می‌سازد."""
        self._clear_rows()

        for memory in memories:
            row = self._create_row(memory)
            self._list_layout.insertWidget(self._list_layout.count() - 1, row)
            self._rows.append(row)

        has_rows = bool(self._rows)
        self._container.setVisible(has_rows)
        self.empty_label.setVisible(not has_rows)

    def _clear_rows(self) -> None:
        """ردیف‌های فعلی را از رابط کاربری حذف می‌کند."""
        for row in self._rows:
            self._list_layout.removeWidget(row)
            row.setParent(None)
            row.deleteLater()

        self._rows.clear()

    def _create_row(self, memory: Memory) -> QWidget:
        """یک ردیف حافظه با چک‌باکس فعال/غیرفعال، ویرایش و حذف می‌سازد."""
        row = QWidget()
        row.setObjectName("memoryRow")

        layout = QHBoxLayout(row)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(10)

        checkbox = QCheckBox()
        checkbox.setObjectName("memoryCheckbox")
        checkbox.setChecked(memory.enabled)
        checkbox.setToolTip("ارسال این واقعیت با هر پیام گفتگو")
        checkbox.toggled.connect(
            lambda checked, memory_id=memory.id: self._toggle_memory(memory_id, checked)
        )
        layout.addWidget(checkbox)

        content_label = QLabel(memory.content)
        content_label.setObjectName("memoryContent")
        content_label.setToolTip(memory.content)
        content_label.setWordWrap(True)
        layout.addWidget(content_label, 1)

        edit_button = QPushButton("ویرایش")
        edit_button.setObjectName("ghostButton")
        edit_button.setFixedHeight(28)
        edit_button.clicked.connect(
            lambda checked=False, memory_id=memory.id: self._edit_memory(memory_id)
        )
        layout.addWidget(edit_button)

        delete_button = QPushButton("حذف")
        delete_button.setObjectName("dangerButton")
        delete_button.setFixedHeight(28)
        delete_button.clicked.connect(
            lambda checked=False, memory_id=memory.id: self._delete_memory(memory_id)
        )
        layout.addWidget(delete_button)

        return row

    def _add_from_composer(self) -> None:
        """واقعیت تازه‌ای از کادر افزودن ذخیره می‌کند."""
        content = self.content_input.text().strip()
        if not content:
            return

        try:
            self._store.add_memory(content)
        except (sqlite3.Error, ValueError) as error:
            self.empty_label.setText(f"افزودن حافظه ناموفق بود: {error}")
            self.empty_label.setVisible(True)
            return

        self.content_input.clear()
        self.content_input.setFocus()
        self.memories_changed.emit()
        self.refresh()

    def _toggle_memory(self, memory_id: int, enabled: bool) -> None:
        """حافظه را فعال یا غیرفعال می‌کند."""
        try:
            self._store.set_memory_enabled(memory_id, enabled)
        except sqlite3.Error as error:
            self.empty_label.setText(f"به‌روزرسانی حافظه ناموفق بود: {error}")
            self.empty_label.setVisible(True)
            return

        self.memories_changed.emit()
        self.refresh()

    def _edit_memory(self, memory_id: int) -> None:
        """متن حافظه را با یک دیالوگ ساده ویرایش می‌کند."""
        try:
            memory = self._store.get_memory(memory_id)
        except sqlite3.Error as error:
            self.empty_label.setText(f"خواندن حافظه ناموفق بود: {error}")
            self.empty_label.setVisible(True)
            return

        if memory is None:
            return

        dialog = QDialog(self)
        dialog.setWindowTitle("ویرایش حافظه")
        dialog.setModal(True)
        dialog.setMinimumWidth(420)

        box_layout = QVBoxLayout(dialog)
        box_layout.addWidget(QLabel("متن واقعیت:"))

        edit_input = QLineEdit(memory.content)
        edit_input.setObjectName("memoryEditInput")
        edit_input.setMaxLength(MAX_MEMORY_CHARS)
        box_layout.addWidget(edit_input)

        buttons_layout = QHBoxLayout()
        buttons_layout.addStretch(1)

        save_button = QPushButton("ذخیره")
        save_button.setObjectName("memoryEditSaveButton")
        cancel_button = QPushButton("انصراف")
        cancel_button.setObjectName("memoryEditCancelButton")
        save_button.setDefault(True)
        buttons_layout.addWidget(cancel_button)
        buttons_layout.addWidget(save_button)
        box_layout.addLayout(buttons_layout)

        save_button.clicked.connect(dialog.accept)
        cancel_button.clicked.connect(dialog.reject)
        edit_input.returnPressed.connect(save_button.click)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        content = edit_input.text().strip()
        if content == memory.content:
            return

        try:
            self._store.update_memory(memory_id, content)
        except (sqlite3.Error, ValueError) as error:
            self.empty_label.setText(f"ذخیره حافظه ناموفق بود: {error}")
            self.empty_label.setVisible(True)
            return

        self.memories_changed.emit()
        self.refresh()

    def _delete_memory(self, memory_id: int) -> None:
        """پس از تأیید، حافظه را حذف می‌کند."""
        answer = QMessageBox.question(
            self,
            "حذف حافظه",
            "این واقعیت برای همیشه حذف شود؟",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if answer != QMessageBox.StandardButton.Yes:
            return

        try:
            self._store.delete_memory(memory_id)
        except sqlite3.Error as error:
            self.empty_label.setText(f"حذف حافظه ناموفق بود: {error}")
            self.empty_label.setVisible(True)
            return

        self.memories_changed.emit()
        self.refresh()
