"""ویجت سبک تب‌های اسناد PDF."""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QWidget

from app.services.pdf_service import PdfDocument


class DocumentTabs(QWidget):
    """نمایش تب‌های سند و ارسال درخواست فعال‌سازی یا بستن آن‌ها."""

    document_activated = Signal(int)
    document_close_requested = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("documentRow")
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(6)
        self._buttons: list[QPushButton] = []
        self._close_buttons: list[QPushButton] = []

    @property
    def buttons(self) -> tuple[QPushButton, ...]:
        """تب‌های فعلی را برای تست و دسترسی محدود UI برمی‌گرداند."""
        return tuple(self._buttons)

    def set_documents(self, documents: Sequence[PdfDocument], active_index: int) -> None:
        """تب‌ها را مطابق سندهای باز بازسازی می‌کند."""
        self._clear()

        for index, document in enumerate(documents):
            tab = QPushButton(_shorten(document.name, 20))
            tab.setObjectName("documentTab")
            tab.setProperty("active", index == active_index)
            tab.setToolTip(f"{document.name} — {document.summary()}\n{document.path}")
            tab.clicked.connect(
                lambda _checked=False, target=index: self.document_activated.emit(target)
            )

            close_button = QPushButton("✕")
            close_button.setObjectName("documentTabClose")
            close_button.setFixedWidth(24)
            close_button.setToolTip(f"بستن «{document.name}»")
            close_button.clicked.connect(
                lambda _checked=False, target=index: self.document_close_requested.emit(target)
            )

            self._buttons.append(tab)
            self._close_buttons.append(close_button)
            self._layout.addWidget(tab)
            self._layout.addWidget(close_button)

        self._layout.addStretch(1)
        self.setVisible(bool(documents))

    def _clear(self) -> None:
        """ویجت‌های قبلی را حذف می‌کند تا state صفحه منبع حقیقت بماند."""
        while self._layout.count():
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

        self._buttons.clear()
        self._close_buttons.clear()


def _shorten(name: str, limit: int) -> str:
    return name if len(name) <= limit else name[: limit - 1] + "…"
