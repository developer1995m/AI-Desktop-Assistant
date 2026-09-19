"""ورودی متن صفحه گفتگو."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QPlainTextEdit, QWidget


class ChatInput(QPlainTextEdit):
    """ورودی چندخطی گفتگو؛ Enter ارسال می‌کند و Shift+Enter خط جدید می‌سازد."""

    send_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self.setObjectName("chatInput")
        self.setPlaceholderText(
            "پیام خود را بنویسید… (Enter برای ارسال، Shift+Enter برای خط جدید)"
        )
        self.setMinimumHeight(84)
        self.setMaximumHeight(168)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """ارسال با Enter و ایجاد خط جدید با Shift+Enter."""
        is_enter = event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
        has_shift = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)

        if is_enter and not has_shift:
            self.send_requested.emit()
            event.accept()
            return

        super().keyPressEvent(event)

    def take_text(self) -> str:
        """متن ورودی را برمی‌گرداند و کادر را خالی می‌کند."""
        text = self.toPlainText().strip()
        self.clear()
        return text
