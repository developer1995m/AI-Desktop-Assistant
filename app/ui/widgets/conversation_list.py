"""بخش «گفتگوهای اخیر» در نوار کناری."""

from __future__ import annotations

from collections.abc import Sequence
from functools import partial

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.services.storage import Conversation

MAX_VISIBLE_CONVERSATIONS = 40


class ConversationList(QWidget):
    """فهرست گفتگوهای ذخیره‌شده با امکان انتخاب و حذف."""

    conversation_selected = Signal(int)
    conversation_delete_requested = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self.setObjectName("conversationSection")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        title_label = QLabel("گفتگوهای اخیر")
        title_label.setObjectName("sectionTitle")
        layout.addWidget(title_label)

        self.empty_label = QLabel("هنوز گفتگویی ذخیره نشده است.")
        self.empty_label.setObjectName("sectionHint")
        self.empty_label.setWordWrap(True)
        layout.addWidget(self.empty_label)

        self._container = QWidget()
        self._container.setObjectName("conversationContainer")

        self._list_layout = QVBoxLayout(self._container)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(4)
        self._list_layout.addStretch(1)

        self._scroll_area = QScrollArea()
        self._scroll_area.setObjectName("conversationScroll")
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll_area.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._scroll_area.setWidget(self._container)
        layout.addWidget(self._scroll_area, 1)

        self._rows: list[QWidget] = []
        self.buttons: dict[int, QPushButton] = {}
        self.delete_buttons: dict[int, QPushButton] = {}

        self.set_conversations([], None)

    def set_conversations(
        self, conversations: Sequence[Conversation], active_id: int | None
    ) -> None:
        """فهرست را از نو می‌سازد و گفتگوی فعال را مشخص می‌کند."""
        self._clear_rows()

        for conversation in list(conversations)[:MAX_VISIBLE_CONVERSATIONS]:
            row = self._create_row(conversation, active_id == conversation.id)
            self._list_layout.insertWidget(self._list_layout.count() - 1, row)
            self._rows.append(row)

        has_conversations = bool(self._rows)
        self._scroll_area.setVisible(has_conversations)
        self.empty_label.setVisible(not has_conversations)

    def _clear_rows(self) -> None:
        """ردیف‌های فعلی را از رابط کاربری حذف می‌کند."""
        for row in self._rows:
            self._list_layout.removeWidget(row)
            row.setParent(None)
            row.deleteLater()

        self._rows.clear()
        self.buttons.clear()
        self.delete_buttons.clear()

    def _create_row(self, conversation: Conversation, is_active: bool) -> QWidget:
        """یک ردیف گفتگو همراه با دکمه انتخاب و دکمه حذف می‌سازد."""
        row = QWidget()
        row.setObjectName("conversationRow")

        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        open_button = QPushButton(conversation.title)
        open_button.setObjectName("conversationButton")
        open_button.setCheckable(True)
        open_button.setChecked(is_active)
        open_button.setToolTip(conversation.title)
        open_button.clicked.connect(partial(self._select, conversation.id))

        delete_button = QPushButton("×")
        delete_button.setObjectName("conversationDeleteButton")
        delete_button.setToolTip("Delete this chat")
        delete_button.setFixedWidth(22)
        delete_button.clicked.connect(partial(self._request_delete, conversation.id))

        layout.addWidget(open_button, 1)
        layout.addWidget(delete_button)

        self.buttons[conversation.id] = open_button
        self.delete_buttons[conversation.id] = delete_button

        return row

    def _select(self, conversation_id: int, checked: bool = False) -> None:
        """انتخاب یک گفتگو را به بیرون اعلام می‌کند."""
        self.conversation_selected.emit(conversation_id)

    def _request_delete(self, conversation_id: int, checked: bool = False) -> None:
        """درخواست حذف یک گفتگو را به بیرون اعلام می‌کند."""
        self.conversation_delete_requested.emit(conversation_id)
