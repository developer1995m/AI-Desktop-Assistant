import sqlite3

from pathlib import Path

from PySide6.QtCore import QRect, Qt, QTimer, Signal
from PySide6.QtGui import QCloseEvent, QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QLabel,
    QHBoxLayout,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app.services.backup import BackupError, auto_backup
from app.services.chat_service import ChatService
from app.services.reminders import pending_reminders, reminder_summary
from app.services.settings import AppSettings
from app.services.storage import ConversationStore
from app.services.ui_state import (
    DEFAULT_HEIGHT,
    DEFAULT_WIDTH,
    MIN_HEIGHT,
    MIN_WIDTH,
    UiStateStore,
)
from app.ui.branding import load_app_icon
from app.ui.pages.chat_page import ChatPage
from app.ui.pages.dashboard_page import DashboardPage
from app.ui.pages.memory_page import MemoryPage
from app.ui.pages.notes_page import NotesPage
from app.ui.pages.pdf_page import PdfPage
from app.ui.pages.settings_page import SettingsPage
from app.ui.pages.tasks_page import TasksPage
from app.ui.theme import DARK, LIGHT, THEMES, stylesheet
from app.ui.tray import ReminderTray
from app.ui.widgets.search_dialog import SearchDialog
from app.ui.widgets.sidebar import Sidebar

REMINDER_INTERVAL_MS = 15 * 60 * 1000  # یادآوری وظایف هر ربع ساعت یک‌بار.


class MainWindow(QMainWindow):
    """پنجره اصلی برنامه و هماهنگ‌کننده صفحات آن."""

    reminder_triggered = Signal(str)

    def __init__(
        self,
        chat_store: ConversationStore | None = None,
        ui_state: UiStateStore | None = None,
    ) -> None:
        super().__init__()

        self.setWindowTitle("AI Desktop Assistant")
        self.setWindowIcon(load_app_icon())
        self.resize(DEFAULT_WIDTH, DEFAULT_HEIGHT)
        self.setMinimumSize(MIN_WIDTH, MIN_HEIGHT)

        self.ui_state = ui_state if ui_state is not None else UiStateStore()
        self._restore_window_state()

        self.settings = AppSettings()
        self.chat_store = chat_store if chat_store is not None else ConversationStore()
        self.last_auto_backup: Path | None = None
        self.chat_service = ChatService(self.settings, self.chat_store)

        self.sidebar = Sidebar()
        self.sidebar.navigation_requested.connect(self.show_page)

        self.page_stack = QStackedWidget()
        self.page_indexes: dict[str, int] = {}

        self.chat_page = ChatPage(self.chat_service, self.chat_store)
        self.chat_page.conversations_updated.connect(self.refresh_conversations)
        self.chat_page.open_settings_requested.connect(self.open_settings_page)
        self.page_indexes["chat"] = self.page_stack.addWidget(self.chat_page)

        self.dashboard_page = DashboardPage(self.chat_store)
        self.dashboard_page.open_conversation_requested.connect(self.open_conversation)
        self.dashboard_page.new_chat_requested.connect(self.start_new_chat)
        self.page_indexes["dashboard"] = self.page_stack.addWidget(self.dashboard_page)

        self.settings_page = SettingsPage(self.settings, self.chat_store)
        self.settings_page.saved.connect(self.chat_page.reload_configuration)
        self.settings_page.data_restored.connect(self.refresh_all_data)
        self.settings_page.theme_changed.connect(self.switch_theme)
        self.page_indexes["settings"] = self.page_stack.addWidget(self.settings_page)

        self.notes_page = NotesPage(self.chat_store)
        self.notes_page.notes_changed.connect(self.dashboard_page.refresh)
        self.page_indexes["notes"] = self.page_stack.addWidget(self.notes_page)

        self.tasks_page = TasksPage(self.chat_store)
        self.tasks_page.tasks_changed.connect(self.dashboard_page.refresh)
        self.page_indexes["tasks"] = self.page_stack.addWidget(self.tasks_page)

        self.memory_page = MemoryPage(self.chat_store)
        self.memory_page.memories_changed.connect(self.dashboard_page.refresh)
        self.memory_page.memories_changed.connect(self.chat_page.refresh_memory_status)
        self.page_indexes["memory"] = self.page_stack.addWidget(self.memory_page)

        self.pdf_page = PdfPage(self.chat_service)
        self.page_indexes["pdf"] = self.page_stack.addWidget(self.pdf_page)

        content_widget = QWidget()
        content_layout = QVBoxLayout(content_widget)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        header = self._create_header()
        content_layout.addWidget(header)
        content_layout.addWidget(self.page_stack)

        main_widget = QWidget()
        main_layout = QHBoxLayout(main_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        main_layout.addWidget(self.sidebar)
        main_layout.addWidget(content_widget)

        self.setCentralWidget(main_widget)
        self._apply_styles()
        self._create_shortcuts()
        self.refresh_conversations()
        self.show_page("dashboard")

        self.sidebar.conversation_selected.connect(self.open_conversation)
        self.sidebar.conversation_delete_requested.connect(self.confirm_conversation_delete)

        # یادآوری وظایف سررسیده: یک‌بار هنگام اجرا و سپس به‌صورت دوره‌ای.
        self.reminder_tray = ReminderTray(
            load_app_icon(),
            on_open_window=self._raise_from_tray,
            on_open_tasks=lambda: (self._raise_from_tray(), self.show_page("tasks")),
            on_quit=self.close,
            parent=self,
        )
        self.reminder_triggered.connect(self._notify_reminder)

        self.reminder_timer = QTimer(self)
        self.reminder_timer.setInterval(REMINDER_INTERVAL_MS)
        self.reminder_timer.timeout.connect(lambda: self.check_task_reminders(quiet=True))
        self.reminder_timer.start()
        self.check_task_reminders(quiet=True)

    def _raise_from_tray(self) -> None:
        """پنجره را از سینی سیستم جلو می‌آورد (حتی اگر کوچک‌شده باشد)."""
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _notify_reminder(self, summary: str) -> None:
        """یادآوری را فقط وقتی اعلان می‌کند که کاربر پنجره را نمی‌بیند.

        اگر برنامه در پیش‌زمینه باشد، چیپ سربرگ کافی است و اعلان سیستمی تکراری
        و آزاردهنده می‌شود.
        """
        if not summary or self.isActiveWindow():
            return

        self.reminder_tray.notify(summary)

    def refresh_all_data(self) -> None:
        """پس از بازیابی پشتیبان، همه صفحه‌ها را با داده تازه همگام می‌کند."""
        self.chat_page.clear_conversation()
        self.chat_page.restore_last_conversation()
        self.chat_page.refresh_memory_status()
        self.notes_page.refresh()
        self.tasks_page.refresh()
        self.memory_page.refresh()
        self.pdf_page.clear_conversation()
        self.refresh_conversations()

    def refresh_conversations(self) -> None:
        """فهرست گفتگوهای ذخیره‌شده را در نوار کناری و داشبورد تازه می‌کند."""
        try:
            conversations = self.chat_store.list_conversations()
        except sqlite3.Error:
            conversations = []

        self.sidebar.set_conversations(conversations, self.chat_page.current_conversation_id)
        self.dashboard_page.refresh()

    def open_settings_page(self) -> None:
        """صفحه تنظیمات را باز می‌کند (مثلاً از بنر راه‌اندازی اولیه صفحه چت)."""
        self.show_page("settings")

    # ----------------------------------------------------------------- یادآوری

    def check_task_reminders(self, *, quiet: bool = False) -> str:
        """وظایف سررسیده را پیدا و گزارش می‌کند.

        در حالت عادی خلاصه در نوار سربرگ نشان داده می‌شود؛ در حالت `quiet` فقط
        وقتی چیزی برای یادآوری هست سیگنال یادآوری صادر می‌شود (برای اعلان سیستم).
        """
        try:
            tasks = self.chat_store.list_tasks()
        except sqlite3.Error:
            tasks = []

        summary = reminder_summary(tasks)
        self.set_reminder_text(summary)

        if quiet and not summary:
            return ""

        self.reminder_triggered.emit(summary)

        return summary

    def start_new_chat(self) -> None:
        """صفحه گفتگو را با گفتگویی خالی باز می‌کند."""
        self.show_page("chat")
        self.chat_page.clear_conversation()
        self.chat_page.chat_input.setFocus()

    def open_conversation(self, conversation_id: int) -> None:
        """صفحه گفتگو را باز می‌کند و گفتگوی انتخاب‌شده را بارگذاری می‌کند."""
        self.show_page("chat")
        self.chat_page.load_conversation(conversation_id)

    def confirm_conversation_delete(self, conversation_id: int) -> None:
        """پیش از حذف گفتگو از کاربر تأیید می‌گیرد."""
        answer = QMessageBox.question(
            self,
            "حذف گفتگو",
            "این گفتگو و همه پیام‌هایش برای همیشه حذف شود؟",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if answer == QMessageBox.StandardButton.Yes:
            self.chat_page.delete_conversation(conversation_id)

    def _create_header(self) -> QWidget:
        """سربرگ با جست‌وجو، یادآور وظایف سررسیده و میان‌برهای ناوبری."""
        header = QWidget()
        header.setObjectName("header")
        header.setFixedHeight(72)

        layout = QHBoxLayout(header)
        layout.setContentsMargins(32, 18, 32, 12)
        layout.setSpacing(12)

        title_label = QLabel("فضای کاری هوشمند شما")
        title_label.setObjectName("headerTitle")
        title_label.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        self.reminder_label = QPushButton()
        self.reminder_label.setObjectName("reminderChip")
        self.reminder_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self.reminder_label.setFixedHeight(32)
        self.reminder_label.setToolTip(
            "وظایف سررسیده؛ کلیک برای بازکردن صفحه وظایف"
        )
        self.reminder_label.clicked.connect(lambda: self.show_page("tasks"))
        self.reminder_label.setVisible(False)

        self.search_button = QPushButton("جست‌وجو  (Ctrl+K)")
        self.search_button.setObjectName("ghostButton")
        self.search_button.setFixedHeight(32)
        self.search_button.clicked.connect(self.open_search)

        QShortcut(QKeySequence("Ctrl+K"), self, activated=self.open_search)

        layout.addWidget(title_label)
        layout.addStretch(1)
        layout.addWidget(self.reminder_label)
        layout.addWidget(self.search_button)

        return header

    def _create_shortcuts(self) -> None:
        """میانبرهای سراسری ناوبری و کنترل گفتگو را ثبت می‌کند."""
        QShortcut(QKeySequence("Ctrl+N"), self, activated=self.start_new_chat)
        QShortcut(
            QKeySequence("Esc"),
            self,
            activated=self._stop_active_response,
        )

        page_keys = ("dashboard", "chat", "notes", "tasks", "pdf", "memory", "settings")
        for index, page_key in enumerate(page_keys, start=1):
            QShortcut(
                QKeySequence(f"Ctrl+{index}"),
                self,
                activated=lambda key=page_key: self.show_page(key),
            )

    def _stop_active_response(self) -> None:
        """پاسخ جریانی صفحه فعال را متوقف می‌کند."""
        current = self.page_stack.currentWidget()
        if current is self.chat_page:
            self.chat_page.stop_response()
        elif current is self.pdf_page:
            self.pdf_page.stop_response()

    def set_reminder_text(self, summary: str) -> None:
        """خلاصه وظایف سررسیده را در سربرگ نشان می‌دهد یا چیپ را پنهان می‌کند."""
        if not summary:
            self.reminder_label.setVisible(False)
            self.reminder_label.setText("")
            return

        self.reminder_label.setText(f"⏰ {summary}")
        self.reminder_label.setVisible(True)

    # ------------------------------------------------------------------ جست‌وجو

    def open_search(self) -> None:
        """پنجره جست‌وجوی سراسری را باز می‌کند."""
        dialog = SearchDialog(self.chat_store, self)
        dialog.result_selected.connect(self.open_search_result)
        self.search_dialog = dialog
        dialog.exec()

    def open_search_result(self, kind: str, item_id: int) -> None:
        """نتیجه انتخاب‌شده در جست‌وجو را در صفحه مربوطه باز می‌کند."""
        if kind == "conversation":
            self.open_conversation(item_id)
        elif kind == "note":
            self.show_page("notes")
            self.notes_page.open_note(item_id)
        elif kind == "task":
            self.show_page("tasks")
            self.tasks_page.refresh()
        elif kind == "memory":
            self.show_page("memory")
            self.memory_page.refresh()

    def show_page(self, page_key: str) -> None:
        """صفحه انتخاب‌شده را در بخش اصلی نمایش می‌دهد."""
        if page_key not in self.page_indexes:
            return

        self.page_stack.setCurrentIndex(self.page_indexes[page_key])
        self.sidebar.set_active_page(page_key)

        # تنظیمات ممکن است بیرون از برنامه تغییر کرده باشد؛ صفحه‌های وابسته را تازه می‌کنیم.
        if page_key == "chat":
            self.chat_page.reload_configuration()
        elif page_key == "pdf":
            self.pdf_page.reload_configuration()
        elif page_key == "settings":
            self.settings_page.reload()
        elif page_key == "memory":
            self.memory_page.refresh()

    # ------------------------------------------------------- وضعیت پنجره

    def _restore_window_state(self) -> None:
        """اندازه و جای پنجره را از اجرای قبلی برمی‌گرداند.

        اگر پنجره ذخیره‌شده روی نمایشگری که دیگر وصل نیست بیفتد، نادیده گرفته می‌شود
        تا برنامه همیشه با پنجره‌ای قابل استفاده بالا بیاید.
        """
        geometry = self.ui_state.window_geometry()

        if geometry is None:
            return

        if not self._is_on_screen(*geometry):
            return

        self.setGeometry(*geometry)

        if self.ui_state.is_maximized():
            self.showMaximized()

    def _is_on_screen(self, x: int, y: int, width: int, height: int) -> bool:
        """آیا بخشی از مستطیل داده‌شده داخل یکی از نمایشگرهای فعلی می‌افتد؟"""
        rectangle = QRect(x, y, width, height)

        return any(
            screen.availableGeometry().intersects(rectangle)
            for screen in QGuiApplication.screens()
        )

    def _save_window_state(self) -> None:
        """اندازه و جای کنونی پنجره را برای اجرای بعدی ذخیره می‌کند.

        در حالت بیشینه، اندازه طبیعی ذخیره می‌شود؛ وگرنه بازگردانی بعدی پنجره را
        بیشینه‌شده و بدون راه برگشت باز می‌کرد.
        """
        maximized = bool(self.windowState() & Qt.WindowState.WindowMaximized)
        geometry = self.normalGeometry() if maximized else self.geometry()

        self.ui_state.save_window(
            geometry.x(),
            geometry.y(),
            geometry.width(),
            geometry.height(),
            maximized=maximized,
        )

    def closeEvent(self, event: QCloseEvent) -> None:
        """قبل از بستن پنجره، پشتیبان می‌گیرد، درخواست‌ها را متوقف و پایگاه‌داده را می‌بندد."""
        self._save_window_state()
        self.create_automatic_backup()
        self.chat_page.shutdown()
        self.pdf_page.shutdown()
        self.settings_page.shutdown()
        self.reminder_tray.hide()
        self.chat_store.close()
        super().closeEvent(event)

    def create_automatic_backup(self) -> Path | None:
        """هنگام بستن برنامه یک پشتیبان خودکار می‌سازد.

        خطای پشتیبان‌گیری هرگز جلوی بسته‌شدن برنامه را نمی‌گیرد؛ فقط نادیده
        گرفته می‌شود چون کاربر منتظر خروج است.
        """
        try:
            self.last_auto_backup = auto_backup(self.chat_store)
        except (BackupError, OSError):
            self.last_auto_backup = None

        return self.last_auto_backup

    def _apply_styles(self) -> None:
        """استایل برنامه را بر پایه تم ذخیره‌شده کاربر اعمال می‌کند."""
        self.current_theme = self.ui_state.theme()
        self.setStyleSheet(stylesheet(self.current_theme))

    def switch_theme(self, theme: str) -> None:
        """تم را عوض می‌کند، ذخیره و بلافاصله اعمال می‌کند.

        تم نامعتبر نادیده گرفته می‌شود تا یک مقدار اشتباه ظاهر برنامه را نشکند.
        """
        if theme not in THEMES or theme == self.current_theme:
            return

        self.current_theme = theme
        self.ui_state.save_theme(theme)
        self.setStyleSheet(stylesheet(theme))

