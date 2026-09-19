from collections.abc import Sequence

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget

from app.services.storage import Conversation
from app.ui.widgets.conversation_list import ConversationList


class Sidebar(QWidget):
    """نوار کناری برنامه، دکمه‌های صفحات و فهرست گفتگوهای ذخیره‌شده."""

    navigation_requested = Signal(str)
    conversation_selected = Signal(int)
    conversation_delete_requested = Signal(int)

    NAVIGATION_ITEMS = [
        ("dashboard", "⌂", "داشبورد"),
        ("chat", "✦", "گفتگو"),
        ("notes", "▤", "یادداشت‌ها"),
        ("tasks", "✓", "وظایف"),
        ("pdf", "▧", "دستیار PDF"),
        ("memory", "◈", "حافظه"),
        ("settings", "⚙", "تنظیمات"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("sidebar")
        self.setFixedWidth(230)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 24, 16, 16)
        layout.setSpacing(8)

        brand_label = QLabel("AI Desktop Assistant")
        brand_label.setObjectName("brandLabel")
        brand_label.setWordWrap(True)
        layout.addWidget(brand_label)
        layout.addSpacing(24)

        self.buttons: dict[str, QPushButton] = {}

        for page_key, icon, title in self.NAVIGATION_ITEMS:
            button = QPushButton(f"  {icon}   {title}")
            button.setObjectName("navigationButton")
            button.setCheckable(True)
            button.setMinimumHeight(42)
            button.clicked.connect(
                lambda checked=False, key=page_key: self.navigation_requested.emit(key)
            )
            self.buttons[page_key] = button
            layout.addWidget(button)

        self.conversations = ConversationList()
        self.conversations.conversation_selected.connect(self.conversation_selected)
        self.conversations.conversation_delete_requested.connect(
            self.conversation_delete_requested
        )
        layout.addWidget(self.conversations, 1)

        version_label = QLabel("Version 0.1.0")
        version_label.setObjectName("versionLabel")
        layout.addWidget(version_label)

    def set_active_page(self, page_key: str) -> None:
        """دکمه صفحه فعلی را فعال و بقیه دکمه‌ها را غیرفعال می‌کند."""
        for key, button in self.buttons.items():
            button.setChecked(key == page_key)

        # فهرست گفتگوها فقط در صفحه گفتگو معنا دارد.
        self.conversations.setVisible(page_key == "chat")

    def set_conversations(
        self, conversations: Sequence[Conversation], active_id: int | None
    ) -> None:
        """فهرست گفتگوهای ذخیره‌شده را به‌روز می‌کند."""
        self.conversations.set_conversations(conversations, active_id)
