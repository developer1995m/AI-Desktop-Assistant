"""صفحه یادداشت‌ها."""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.services.storage import ConversationStore, Note

PREVIEW_MAX_LENGTH = 140


def preview_text(text: str, max_length: int = PREVIEW_MAX_LENGTH) -> str:
    """متن یادداشت را به پیش‌نمایش تک‌خطی کوتاه تبدیل می‌کند."""
    preview = " ".join(text.split())

    if not preview:
        return "—"

    if len(preview) > max_length:
        return preview[: max_length - 1].rstrip() + "…"

    return preview


class NotesPage(QWidget):
    """ایجاد، ویرایش و حذف یادداشت‌های محلی."""

    notes_changed = Signal()

    ALL_TAGS_LABEL = "همهٔ برچسب‌ها"

    def __init__(self, store: ConversationStore, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self.setObjectName("notesPage")

        self._store = store
        self._current_note_id: int | None = None
        self._rows: list[QWidget] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 24, 32, 24)
        layout.setSpacing(16)

        layout.addWidget(self._create_heading())

        self.editor = self._create_editor()
        self.list_view = self._create_list_view()

        # دو حالت صفحه: فهرست یادداشت‌ها و ویرایش یک یادداشت.
        self.mode_stack = QStackedWidget()
        self.mode_stack.addWidget(self.list_view)
        self.mode_stack.addWidget(self.editor)
        layout.addWidget(self.mode_stack, 1)

        self.refresh()

    # ------------------------------------------------------------------ ساخت رابط

    def _create_heading(self) -> QWidget:
        """سربرگ صفحه با دکمه یادداشت جدید."""
        heading = QWidget()

        layout = QHBoxLayout(heading)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        title_label = QLabel("یادداشت‌ها")
        title_label.setObjectName("pageTitle")

        self.new_note_button = QPushButton("یادداشت جدید")
        self.new_note_button.setObjectName("primaryButton")
        self.new_note_button.setFixedHeight(36)
        self.new_note_button.clicked.connect(self._start_new_note)

        layout.addWidget(title_label)
        layout.addStretch(1)
        layout.addWidget(self.new_note_button)

        return heading

    def _create_list_view(self) -> QWidget:
        """فهرست یادداشت‌ها با اسکرول."""
        container = QWidget()
        container.setObjectName("notesListContainer")

        outer_layout = QVBoxLayout(container)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(10)

        self.filter_bar = self._create_filter_bar()
        outer_layout.addWidget(self.filter_bar)

        self.empty_label = QLabel("هنوز یادداشتی ندارید؛ یکی بسازید.")
        self.empty_label.setObjectName("notesEmpty")
        self.empty_label.setWordWrap(True)
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        outer_layout.addWidget(self.empty_label)

        self._notes_container = QWidget()
        self._notes_container.setObjectName("notesContainer")

        self._list_layout = QVBoxLayout(self._notes_container)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(8)
        self._list_layout.addStretch(1)

        scroll_area = QScrollArea()
        scroll_area.setObjectName("notesScroll")
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_area.setWidget(self._notes_container)

        outer_layout.addWidget(scroll_area, 1)

        return container

    def _create_filter_bar(self) -> QWidget:
        """نوار فیلتر برچسب‌ها و شمارنده یادداشت‌ها.

        تا وقتی هیچ برچسبی ساخته نشده باشد پنهان می‌ماند تا صفحه شلوغ نشود.
        """
        bar = QWidget()

        layout = QHBoxLayout(bar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        filter_label = QLabel("برچسب:")
        filter_label.setObjectName("pageDescription")

        self.tag_filter = QComboBox()
        self.tag_filter.setObjectName("taskFilterCombo")
        self.tag_filter.setMinimumWidth(160)
        self.tag_filter.addItem(self.ALL_TAGS_LABEL, "")
        self.tag_filter.currentIndexChanged.connect(self._on_tag_filter_changed)

        self.notes_counter = QLabel()
        self.notes_counter.setObjectName("noteCounter")

        layout.addWidget(filter_label)
        layout.addWidget(self.tag_filter)
        layout.addStretch(1)
        layout.addWidget(self.notes_counter)

        bar.setVisible(False)
        return bar

    def selected_tag(self) -> str:
        """برچسب فعال در فیلتر؛ رشته خالی یعنی «همه»."""
        return self.tag_filter.currentData() or ""

    def _on_tag_filter_changed(self, _index: int) -> None:
        """با تغییر برچسب، فهرست را دوباره می‌سازد."""
        self.refresh()

    def _sync_tag_filter(self, tags: Sequence[tuple[str, int]]) -> None:
        """گزینه‌های فیلتر را تازه می‌کند و انتخاب فعلی کاربر را نگه می‌دارد."""
        previous = self.selected_tag()

        self.tag_filter.blockSignals(True)
        self.tag_filter.clear()
        self.tag_filter.addItem(self.ALL_TAGS_LABEL, "")

        for tag, count in tags:
            self.tag_filter.addItem(f"{tag} ({count})", tag)

        index = self.tag_filter.findData(previous)
        self.tag_filter.setCurrentIndex(max(0, index))
        self.tag_filter.blockSignals(False)

        self.filter_bar.setVisible(bool(tags))

    def _create_editor(self) -> QWidget:
        """ویرایشگر یادداشت با عنوان، متن و دکمه‌های ذخیره/حذف."""
        container = QWidget()
        container.setObjectName("notesEditorContainer")

        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        self.title_input = QLineEdit()
        self.title_input.setObjectName("noteTitleInput")
        self.title_input.setPlaceholderText("عنوان یادداشت…")
        self.title_input.setFixedHeight(38)
        layout.addWidget(self.title_input)

        self.tags_input = QLineEdit()
        self.tags_input.setObjectName("noteTagsInput")
        self.tags_input.setPlaceholderText("برچسب‌ها، جدا شده با کاما (اختیاری)")
        self.tags_input.setFixedHeight(34)
        layout.addWidget(self.tags_input)

        self.content_input = QTextEdit()
        self.content_input.setObjectName("noteContentInput")
        self.content_input.setPlaceholderText("متن یادداشت…")
        layout.addWidget(self.content_input, 1)

        buttons_layout = QHBoxLayout()
        buttons_layout.setSpacing(10)

        self.back_button = QPushButton("بازگشت")
        self.back_button.setObjectName("ghostButton")
        self.back_button.setFixedHeight(36)
        self.back_button.clicked.connect(self.show_list)

        self.delete_button = QPushButton("حذف یادداشت")
        self.delete_button.setObjectName("dangerButton")
        self.delete_button.setFixedHeight(36)
        self.delete_button.clicked.connect(self._delete_current_note)

        self.save_button = QPushButton("ذخیره")
        self.save_button.setObjectName("primaryButton")
        self.save_button.setFixedHeight(36)
        self.save_button.clicked.connect(self._save_editor)

        buttons_layout.addWidget(self.back_button)
        buttons_layout.addStretch(1)
        buttons_layout.addWidget(self.delete_button)
        buttons_layout.addWidget(self.save_button)

        layout.addLayout(buttons_layout)

        return container

    # --------------------------------------------------------------------- ناوبری

    def show_list(self) -> None:
        """فهرست یادداشت‌ها را نشان می‌دهد."""
        self.mode_stack.setCurrentWidget(self.list_view)

    def show_editor(self, note: Note | None) -> None:
        """ویرایشگر را برای یادداشت داده‌شده (یا یادداشت جدید) باز می‌کند."""
        self._current_note_id = note.id if note is not None else None
        self.title_input.setText(note.title if note is not None else "")
        self.tags_input.setText(", ".join(note.tags) if note is not None else "")
        self.content_input.setPlainText(note.content if note is not None else "")
        self.delete_button.setVisible(note is not None)
        self.title_input.setFocus()
        self.mode_stack.setCurrentWidget(self.editor)

    # --------------------------------------------------------------------- رفتار

    def refresh(self) -> None:
        """فهرست یادداشت‌ها را از پایگاه‌داده تازه می‌کند.

        فهرست و شمارنده پیش از فیلتر پر می‌شوند تا حذف یا ویرایش یادداشت با فیلتر
        فعال هم نتیجه درستی بدهد.
        """
        try:
            notes = self._store.list_notes()
            tags = self._store.list_note_tags()
        except sqlite3.Error as error:
            self.empty_label.setText(f"خواندن یادداشت‌ها ناموفق بود: {error}")
            notes = []
            tags = []

        # اگر برچسب انتخاب‌شده با آخرین یادداشتش پاک شده باشد، فیلتر آزاد می‌شود.
        self._sync_tag_filter(tags)
        selected = self.selected_tag()
        visible = [note for note in notes if self._has_tag(note, selected)] if selected else notes

        self._fill_rows(visible)
        self._update_counter(len(visible), len(notes))

        if self.mode_stack.currentWidget() is self.editor:
            self.show_list()

    @staticmethod
    def _has_tag(note: Note, tag: str) -> bool:
        """آیا یادداشت برچسب داده‌شده را دارد؟ (بدون توجه به بزرگی و کوچکی حروف)"""
        key = tag.casefold()

        return any(item.casefold() == key for item in note.tags)

    def _update_counter(self, visible: int, total: int) -> None:
        """شمارنده یادداشت‌ها را با توجه به فیلتر فعال نشان می‌دهد."""
        if total == 0:
            self.notes_counter.setText("")
            return

        if visible == total:
            self.notes_counter.setText(f"{total} یادداشت")
            return

        self.notes_counter.setText(f"{visible} از {total} یادداشت")

    def _fill_rows(self, notes: Sequence[Note]) -> None:
        """ردیف‌های فهرست را از نو می‌سازد."""
        self._clear_rows()

        for note in notes:
            row = self._create_row(note)
            self._list_layout.insertWidget(self._list_layout.count() - 1, row)
            self._rows.append(row)

        has_rows = bool(self._rows)
        self._notes_container.setVisible(has_rows)
        self.empty_label.setVisible(not has_rows)
        self.empty_label.setText(
            "یادداشتی با این برچسب نیست."
            if self.selected_tag()
            else "هنوز یادداشتی ندارید؛ یکی بسازید."
        )

    def _clear_rows(self) -> None:
        """ردیف‌های فعلی را از رابط کاربری حذف می‌کند."""
        for row in self._rows:
            self._list_layout.removeWidget(row)
            row.setParent(None)
            row.deleteLater()

        self._rows.clear()

    def _create_row(self, note: Note) -> QWidget:
        """یک ردیف یادداشت با عنوان، پیش‌نمایش و دکمه‌های بازکردن/حذف می‌سازد."""
        row = QWidget()
        row.setObjectName("noteRow")

        layout = QHBoxLayout(row)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(12)

        text_layout = QVBoxLayout()
        text_layout.setSpacing(2)

        title_label = QLabel(note.title)
        title_label.setObjectName("noteRowTitle")
        title_label.setToolTip(note.title)

        preview_label = QLabel(preview_text(note.content))
        preview_label.setObjectName("noteRowPreview")

        text_layout.addWidget(title_label)
        text_layout.addWidget(preview_label)

        if note.tags:
            text_layout.addWidget(self._create_tag_chips(note.tags))

        layout.addLayout(text_layout, 1)

        delete_button = QPushButton("حذف")
        delete_button.setObjectName("dangerButton")
        delete_button.setFixedHeight(28)
        delete_button.clicked.connect(
            lambda checked=False, note_id=note.id: self._delete_note(note_id)
        )
        layout.addWidget(delete_button)

        open_button = QPushButton("بازکردن")
        open_button.setObjectName("ghostButton")
        open_button.setFixedHeight(28)
        open_button.clicked.connect(
            lambda checked=False, note_id=note.id: self._open_note(note_id)
        )
        layout.addWidget(open_button)

        return row

    @staticmethod
    def _create_tag_chips(tags: Sequence[str]) -> QWidget:
        """چیپ‌های کوچک برچسب‌های یک یادداشت را می‌سازد."""
        container = QWidget()

        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 2, 0, 0)
        layout.setSpacing(6)

        for tag in tags:
            chip = QLabel(tag)
            chip.setObjectName("tagChip")
            layout.addWidget(chip)

        layout.addStretch(1)
        return container

    def _start_new_note(self) -> None:
        """ویرایشگر را برای یادداشت تازه باز می‌کند."""
        self.show_editor(None)

    def open_note(self, note_id: int) -> None:
        """یادداشت مشخصی را برای ویرایش باز می‌کند (برای جست‌وجوی سراسری)."""
        self._open_note(note_id)

    def _open_note(self, note_id: int) -> None:
        """یادداشت را در ویرایشگر باز می‌کند."""
        try:
            note = self._store.get_note(note_id)
        except sqlite3.Error as error:
            self.empty_label.setText(f"بازکردن یادداشت ناموفق بود: {error}")
            return

        if note is not None:
            self.show_editor(note)

    def _save_editor(self) -> None:
        """یادداشت جاری را ذخیره می‌کند."""
        title = self.title_input.text().strip()
        content = self.content_input.toPlainText()

        if not title and not content.strip():
            self.empty_label.setText("عنوان یا متنی بنویسید.")
            self.empty_label.setVisible(True)
            return

        tags = self.tags_input.text()

        try:
            if self._current_note_id is None:
                self._store.create_note(
                    title or preview_text(content, max_length=120), content, tags=tags
                )
            else:
                self._store.update_note(self._current_note_id, title, content, tags=tags)
        except sqlite3.Error as error:
            self.empty_label.setText(f"ذخیره یادداشت ناموفق بود: {error}")
            self.empty_label.setVisible(True)
            return

        self.notes_changed.emit()
        self.refresh()

    def _delete_current_note(self) -> None:
        """یادداشت بازشده در ویرایشگر را حذف می‌کند."""
        if self._current_note_id is None:
            self.show_list()
            return

        self._delete_note(self._current_note_id)

    def _delete_note(self, note_id: int) -> None:
        """پس از تأیید، یادداشت را حذف می‌کند."""
        answer = QMessageBox.question(
            self,
            "حذف یادداشت",
            "این یادداشت برای همیشه حذف شود؟",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if answer != QMessageBox.StandardButton.Yes:
            return

        try:
            self._store.delete_note(note_id)
        except sqlite3.Error as error:
            self.empty_label.setText(f"حذف یادداشت ناموفق بود: {error}")
            self.empty_label.setVisible(True)
            return

        if note_id == self._current_note_id:
            self._current_note_id = None

        self.notes_changed.emit()
        self.refresh()
