"""پنجره جست‌وجوی سراسری روی گفتگوها، یادداشت‌ها، وظایف و حافظه."""

from __future__ import annotations

from functools import partial

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.services.storage import SEARCH_KINDS, ConversationStore, SearchHit

KIND_LABELS = {
    "conversation": "گفتگوها",
    "note": "یادداشت‌ها",
    "task": "وظیفه‌ها",
    "memory": "حافظه‌ها",
}

EMPTY_HINT = "برای جست‌وجو حداقل یک حرف بنویسید."
NO_RESULTS_HINT = "چیزی پیدا نشد."


class SearchDialog(QDialog):
    """جست‌وجو در همه بخش‌های برنامه و باز کردن نتیجه انتخاب‌شده."""

    result_selected = Signal(str, int)

    def __init__(self, store: ConversationStore, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self.setObjectName("searchDialog")
        self.setWindowTitle("جست‌وجوی سراسری")
        self.setModal(True)
        self.resize(560, 460)

        self._store = store
        self._rows: list[QWidget] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)

        self.search_input = QLineEdit()
        self.search_input.setObjectName("searchInput")
        self.search_input.setPlaceholderText("جست‌وجو در گفتگوها، یادداشت‌ها، وظیفه‌ها و حافظه…")
        self.search_input.textChanged.connect(self.refresh)
        layout.addWidget(self.search_input)

        layout.addWidget(self._create_results_area(), 1)

        self.hint_label = QLabel(EMPTY_HINT)
        self.hint_label.setObjectName("searchHint")
        self.hint_label.setWordWrap(True)
        layout.addWidget(self.hint_label)

        close_button = QPushButton("بستن")
        close_button.setObjectName("ghostButton")
        close_button.setFixedHeight(32)
        close_button.clicked.connect(self.reject)

        footer = QHBoxLayout()
        footer.addWidget(self.hint_label, 1)
        footer.addWidget(close_button, 0)
        layout.addLayout(footer)

        self.search_input.setFocus()

    # ------------------------------------------------------------------ ساخت رابط

    def _create_results_area(self) -> QScrollArea:
        """ناحیه اسکرول‌شونده نتایج."""
        self.results_container = QWidget()
        self.results_container.setObjectName("searchResultsContainer")

        self.results_layout = QVBoxLayout(self.results_container)
        self.results_layout.setContentsMargins(10, 10, 10, 10)
        self.results_layout.setSpacing(8)
        self.results_layout.addStretch(1)

        self.scroll_area = QScrollArea()
        self.scroll_area.setObjectName("searchResults")
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll_area.setWidget(self.results_container)

        return self.scroll_area

    # --------------------------------------------------------------------- رفتار

    def refresh(self) -> None:
        """نتیجه‌ها را بر اساس متن کادر جست‌وجو دوباره می‌سازد."""
        query = self.search_input.text().strip()
        self._clear_results()

        if not query:
            self.hint_label.setText(EMPTY_HINT)
            return

        try:
            hits = self._store.search(query)
        except Exception as error:  # noqa: BLE001 - خطای پایگاه‌داده نباید پنجره را ببندد
            self.hint_label.setText(f"جست‌وجو ناموفق بود: {error}")
            return

        if not hits:
            self.hint_label.setText(NO_RESULTS_HINT)
            return

        counts = {kind: 0 for kind in SEARCH_KINDS}

        for kind in SEARCH_KINDS:
            for hit in hits:
                if hit.kind != kind:
                    continue

                if counts[kind] == 0:
                    group = QLabel(KIND_LABELS[kind])
                    group.setObjectName("searchGroup")
                    self.results_layout.insertWidget(self.results_layout.count() - 1, group)

                counts[kind] += 1
                self._add_result_row(hit)

        total = sum(counts.values())
        self.hint_label.setText(f"{total} نتیجه — یک نتیجه را برای باز کردن انتخاب کنید.")

    def _add_result_row(self, hit: SearchHit) -> None:
        """یک ردیف نتیجه را به فهرست اضافه می‌کند."""
        row = QPushButton()
        row.setObjectName("searchResult")
        row.setCursor(Qt.CursorShape.PointingHandCursor)
        row.clicked.connect(partial(self._open_hit, hit))

        layout = QVBoxLayout(row)
        layout.setContentsMargins(12, 9, 12, 9)
        layout.setSpacing(3)

        title_label = QLabel(hit.title or "بدون عنوان")
        title_label.setObjectName("searchResultTitle")
        title_label.setWordWrap(True)

        snippet_label = QLabel(hit.snippet or "")
        snippet_label.setObjectName("searchResultSnippet")
        snippet_label.setWordWrap(True)

        layout.addWidget(title_label)
        layout.addWidget(snippet_label)

        self.results_layout.insertWidget(self.results_layout.count() - 1, row)
        self._rows.append(row)

    def _clear_results(self) -> None:
        """ردیف‌ها و سرگروه‌های قبلی را پاک می‌کند."""
        widgets: list[QWidget] = list(self._rows)

        # سرگروها هم در همین چیدمان هستند، پس همه با هم جمع می‌شوند و بعد پاک.
        for index in range(self.results_layout.count()):
            item = self.results_layout.itemAt(index)
            widget = item.widget() if item is not None else None

            if isinstance(widget, QLabel):
                widgets.append(widget)

        self._rows.clear()

        for widget in widgets:
            self.results_layout.removeWidget(widget)
            widget.setParent(None)
            widget.deleteLater()

    def _open_hit(self, hit: SearchHit) -> None:
        """نتیجه انتخاب‌شده را اعلام می‌کند و پنجره را می‌بندد."""
        self.result_selected.emit(hit.kind, hit.id)
        self.accept()
