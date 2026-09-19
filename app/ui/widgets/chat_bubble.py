"""حباب‌های نمایش پیام در صفحه گفتگو."""

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QGuiApplication
import shiboken6
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

BUBBLE_OBJECT_NAMES = {
    "user": "userBubble",
    "assistant": "assistantBubble",
    "error": "errorBubble",
}

MAX_BUBBLE_WIDTH = 620


class MessageBubble(QFrame):
    """حباب نمایش یک پیام با ظاهر متفاوت برای کاربر، دستیار و خطاها."""

    def __init__(self, role: str, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self.role = role
        self.setObjectName(BUBBLE_OBJECT_NAMES.get(role, "assistantBubble"))
        self.setMaximumWidth(MAX_BUBBLE_WIDTH)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)

        self.text_label = QLabel(text)
        self.text_label.setObjectName("bubbleText")
        self.text_label.setWordWrap(True)
        self.text_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        layout.addWidget(self.text_label)

        # دکمه کپی فقط برای پاسخ‌های دستیار؛ کاربر متن خودش را از دست دارد.
        self.copy_button = None

        if role == "assistant":
            self.copy_button = QPushButton("کپی")
            self.copy_button.setObjectName("bubbleCopyButton")
            self.copy_button.setCursor(Qt.CursorShape.PointingHandCursor)
            self.copy_button.setFixedHeight(24)
            self.copy_button.setToolTip("کپی پاسخ در کلیپ‌بورد")
            self.copy_button.clicked.connect(self.copy_text)

            row = QHBoxLayout()
            row.setContentsMargins(0, 2, 0, 0)
            row.addStretch(1)
            row.addWidget(self.copy_button)
            layout.addLayout(row)

    def text(self) -> str:
        """متن فعلی حباب."""
        return self.text_label.text()

    def set_text(self, text: str) -> None:
        """متن حباب را جایگزین می‌کند."""
        self.text_label.setText(text)

    def append_text(self, chunk: str) -> None:
        """متن جدید را به انتهای حباب اضافه می‌کند تا پاسخ جریانی نمایش داده شود."""
        self.text_label.setText(self.text_label.text() + chunk)

    def copy_text(self) -> None:
        """متن پاسخ را در کلیپ‌بورد سیستم کپی می‌کند و دکمه را گزارش می‌دهد."""
        clipboard = QGuiApplication.clipboard()
        clipboard.setText(self.text_label.text())

        if self.copy_button is not None:
            self.copy_button.setText("کپی شد ✓")

            QTimer.singleShot(1600, self._restore_copy_button)

    def _restore_copy_button(self) -> None:
        """متن دکمه کپی را پس از بازه کوتاه به حالت اول برمی‌گرداند."""
        if self.copy_button is not None and shiboken6.isValid(self):
            self.copy_button.setText("کپی")
