"""صفحه داشبورد؛ خلاصه‌ای از گفتگوهای ذخیره‌شده."""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.services.storage import Conversation, ConversationStore, StoreStats

PREVIEW_MAX_LENGTH = 120
RECENT_ROW_LIMIT = 8


def preview_text(text: str | None, max_length: int = PREVIEW_MAX_LENGTH) -> str:
    """متن یک پیام را به پیش‌نمایش تک‌خطی کوتاه تبدیل می‌کند."""
    preview = " ".join((text or "").split())

    if not preview:
        return "—"

    if len(preview) > max_length:
        return preview[: max_length - 1].rstrip() + "…"

    return preview


class StatCard(QFrame):
    """کارت نمایش یک عدد آماری."""

    def __init__(self, title: str, object_name: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self.setObjectName(object_name)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(4)

        self.value_label = QLabel("0")
        self.value_label.setObjectName("statValue")
        layout.addWidget(self.value_label)

        title_label = QLabel(title)
        title_label.setObjectName("statTitle")
        layout.addWidget(title_label)

    def set_value(self, value: int) -> None:
        """عدد کارت را جایگزین می‌کند."""
        self.value_label.setText(f"{value:,}")


class DashboardPage(QWidget):
    """نمای کلی از گفتگوهای ذخیره‌شده و آخرین فعالیت‌ها."""

    open_conversation_requested = Signal(int)
    new_chat_requested = Signal()

    def __init__(self, store: ConversationStore, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self.setObjectName("dashboardPage")

        self._store = store

        page_layout = QVBoxLayout(self)
        page_layout.setContentsMargins(32, 24, 32, 24)
        page_layout.setSpacing(16)

        page_layout.addWidget(self._create_heading())
        page_layout.addWidget(self._create_stat_cards())

        self.recent_frame = self._create_recent_frame()
        page_layout.addWidget(self.recent_frame, 1)

        self.refresh()

    # ------------------------------------------------------------------ ساخت رابط

    def _create_heading(self) -> QWidget:
        """سربرگ صفحه شامل عنوان و دکمه شروع گفتگوی جدید."""
        heading = QWidget()

        layout = QHBoxLayout(heading)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        title_label = QLabel("داشبورد")
        title_label.setObjectName("pageTitle")

        self.new_chat_button = QPushButton("گفتگوی جدید")
        self.new_chat_button.setObjectName("primaryButton")
        self.new_chat_button.setFixedHeight(36)
        self.new_chat_button.clicked.connect(self.new_chat_requested)

        layout.addWidget(title_label)
        layout.addStretch(1)
        layout.addWidget(self.new_chat_button)

        return heading

    def _create_stat_cards(self) -> QWidget:
        """ردیف کارت‌های آماری را می‌سازد."""
        container = QWidget()

        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        self.chats_card = StatCard("گفتگوهای ذخیره‌شده", "statCardChats")
        self.messages_card = StatCard("کل پیام‌ها", "statCardMessages")
        self.sent_card = StatCard("پیام‌های شما", "statCardSent")
        self.replies_card = StatCard("پاسخ‌های دستیار", "statCardReplies")

        for card in (self.chats_card, self.messages_card, self.sent_card, self.replies_card):
            layout.addWidget(card, 1)

        return container

    def _create_recent_frame(self) -> QFrame:
        """کادر «گفتگوهای اخیر» با ردیف‌های قابل کلیک."""
        frame = QFrame()
        frame.setObjectName("recentFrame")

        frame_layout = QVBoxLayout(frame)
        frame_layout.setContentsMargins(20, 16, 20, 16)
        frame_layout.setSpacing(10)

        title_label = QLabel("گفتگوهای اخیر")
        title_label.setObjectName("recentTitle")
        frame_layout.addWidget(title_label)

        self.empty_label = QLabel(
            "هنوز گفتگویی ذخیره نشده است؛ یک گفتگوی جدید شروع کنید."
        )
        self.empty_label.setObjectName("recentEmpty")
        self.empty_label.setWordWrap(True)
        frame_layout.addWidget(self.empty_label)

        self._container = QWidget()
        self._container.setObjectName("recentContainer")

        self._list_layout = QVBoxLayout(self._container)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(6)
        self._list_layout.addStretch(1)

        scroll_area = QScrollArea()
        scroll_area.setObjectName("recentScroll")
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_area.setWidget(self._container)

        frame_layout.addWidget(scroll_area, 1)

        self._rows: list[QWidget] = []

        return frame

    # --------------------------------------------------------------------- به‌روزرسانی

    def refresh(self) -> None:
        """آمار و فهرست گفتگوهای اخیر را از پایگاه‌داده تازه می‌کند."""
        try:
            stats = self._store.stats()
            conversations = self._store.list_conversations(limit=RECENT_ROW_LIMIT)
        except sqlite3.Error:
            stats = StoreStats(0, 0, 0, 0)
            conversations = []

        self.chats_card.set_value(stats.conversation_count)
        self.messages_card.set_value(stats.message_count)
        self.sent_card.set_value(stats.user_message_count)
        self.replies_card.set_value(stats.assistant_message_count)

        self._fill_recent_rows(conversations)

    def _fill_recent_rows(self, conversations: Sequence[Conversation]) -> None:
        """ردیف‌های گفتگوهای اخیر را از نو می‌سازد."""
        self._clear_rows()

        for conversation in conversations:
            row = self._create_row(conversation)
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

    def _create_row(self, conversation: Conversation) -> QWidget:
        """یک ردیف گفتگو با عنوان، پیش‌نمایش آخرین پیام و دکمه بازکردن می‌سازد."""
        row = QWidget()
        row.setObjectName("recentRow")

        layout = QHBoxLayout(row)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(12)

        text_layout = QVBoxLayout()
        text_layout.setSpacing(2)

        title_label = QLabel(conversation.title)
        title_label.setObjectName("recentRowTitle")
        title_label.setToolTip(conversation.title)

        preview_label = QLabel(preview_text(self._store.last_message(conversation.id)))
        preview_label.setObjectName("recentRowPreview")

        text_layout.addWidget(title_label)
        text_layout.addWidget(preview_label)
        layout.addLayout(text_layout, 1)

        open_button = QPushButton("بازکردن")
        open_button.setObjectName("ghostButton")
        open_button.setCursor(Qt.CursorShape.PointingHandCursor)
        open_button.clicked.connect(
            lambda checked=False, conversation_id=conversation.id: (
                self.open_conversation_requested.emit(conversation_id)
            )
        )
        layout.addWidget(open_button)

        return row
