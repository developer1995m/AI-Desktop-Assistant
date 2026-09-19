"""صفحه تنظیمات برنامه."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QComboBox,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

MODEL_OPTIONS = (
    "gpt-4o-mini",
    "gpt-4o",
    "gpt-4.1-mini",
    "gpt-4.1",
    "o3-mini",
)


class ModelComboBox(QComboBox):
    """فهرست مدل با API سازگار با ورودی متنی قدیمی صفحه تنظیمات."""

    def __init__(self) -> None:
        super().__init__()
        self.setEditable(True)
        self.addItems(MODEL_OPTIONS)

    def text(self) -> str:
        return self.currentText()

    def setText(self, value: str) -> None:
        self.setEditText(value)

from app.services.backup import (
    TABLE_LABELS,
    BackupError,
    default_backup_folder,
    default_backup_name,
    export_backup,
    import_backup,
    read_backup,
    summarise,
)
from app.services.chat_service import ChatService
from app.services.settings import (
    DEFAULT_MAX_RETRIES,
    DEFAULT_TEMPERATURE,
    DEFAULT_TIMEOUT_SECONDS,
    MAX_RETRIES_LIMIT,
    MAX_TEMPERATURE,
    MAX_TIMEOUT_SECONDS,
    MIN_TIMEOUT_SECONDS,
    MIN_TEMPERATURE,
    AppSettings,
)
from app.services.storage import ConversationStore
from app.ui.theme import DARK as THEME_DARK
from app.ui.theme import LIGHT as THEME_LIGHT
from app.ui.theme import normalise_theme
from app.ui.workers import ConnectionTestWorker


class SettingsPage(QWidget):
    """ویرایش تنظیمات سرویس هوش مصنوعی و پشتیبان‌گیری از داده‌های برنامه."""

    saved = Signal()
    data_restored = Signal()
    theme_changed = Signal(str)

    def __init__(
        self,
        settings: AppSettings,
        store: ConversationStore | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)

        self.setObjectName("settingsPage")

        self._settings = settings
        self._store = store
        self._test_worker: ConnectionTestWorker | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 24, 32, 24)
        layout.setSpacing(16)

        layout.addWidget(self._create_heading())
        layout.addWidget(self._create_form_frame(), 1)
        layout.addWidget(self._create_theme_row())
        layout.addWidget(self._create_data_frame())

        self.reload()

    # ------------------------------------------------------------------ ساخت رابط

    def _configure_input(self, widget: QWidget) -> None:
        """اندازه فیلد را ثابت نگه می‌دارد تا ردیف‌های فرم روی هم نیفتند."""
        widget.setFixedHeight(42)
        widget.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )

    def _add_form_row(
        self,
        form_layout: QVBoxLayout,
        label_text: str,
        widget: QWidget,
    ) -> None:
        """یک ردیف پایدار با برچسب راست‌چین و فیلد قابل‌گسترش می‌سازد."""
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(14)

        label = QLabel(label_text)
        label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        label.setMinimumWidth(72)

        row_layout.addWidget(label)
        row_layout.addWidget(widget, 1)
        form_layout.addWidget(row)

    def _create_heading(self) -> QWidget:
        """سربرگ صفحه تنظیمات."""
        heading = QWidget()

        layout = QVBoxLayout(heading)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        title_label = QLabel("تنظیمات")
        title_label.setObjectName("pageTitle")
        layout.addWidget(title_label)

        description_label = QLabel(
            "مقادیر ذخیره‌شده در فایل .env پروژه نوشته می‌شوند؛ متغیر محیطی سیستم "
            "در صورت وجود همیشه اولویت دارد."
        )
        description_label.setObjectName("pageDescription")
        description_label.setWordWrap(True)
        layout.addWidget(description_label)

        return heading

    def _create_form_frame(self) -> QFrame:
        """کادر فرم تنظیمات."""
        frame = QFrame()
        frame.setObjectName("settingsFrame")
        frame.setMaximumWidth(640)
        frame.setMinimumHeight(470)

        frame_layout = QVBoxLayout(frame)
        frame_layout.setContentsMargins(20, 18, 20, 18)
        frame_layout.setSpacing(14)

        form = QWidget()
        form_layout = QVBoxLayout(form)
        form_layout.setContentsMargins(0, 0, 0, 0)
        form_layout.setSpacing(14)

        self.api_key_input = QLineEdit()
        self.api_key_input.setObjectName("settingsInput")
        self._configure_input(self.api_key_input)
        self.api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_input.setPlaceholderText("sk-…")
        self._add_form_row(form_layout, "کلید API", self.api_key_input)

        self.model_input = ModelComboBox()
        self.model_input.setObjectName("settingsInput")
        self._configure_input(self.model_input)
        self.model_input.setPlaceholderText(AppSettings.DEFAULT_MODEL)
        self.model_input.setToolTip(
            "یک مدل را از فهرست انتخاب کنید یا نام مدل سفارشی را وارد کنید."
        )
        self._add_form_row(form_layout, "مدل", self.model_input)

        self.base_url_input = QLineEdit()
        self.base_url_input.setObjectName("settingsInput")
        self._configure_input(self.base_url_input)
        self.base_url_input.setPlaceholderText("https://api.openai.com/v1 (اختیاری)")
        self._add_form_row(form_layout, "Base URL", self.base_url_input)

        self.timeout_input = QLineEdit()
        self.timeout_input.setObjectName("settingsInput")
        self._configure_input(self.timeout_input)
        self.timeout_input.setPlaceholderText(f"{DEFAULT_TIMEOUT_SECONDS:g} (پیش‌فرض)")
        self.timeout_input.setToolTip(
            "بیشترین زمانی که برنامه برای هر پاسخ منتظر می‌ماند (ثانیه)."
        )
        self._add_form_row(form_layout, "زمان انتظار", self.timeout_input)

        self.retries_input = QLineEdit()
        self.retries_input.setObjectName("settingsInput")
        self._configure_input(self.retries_input)
        self.retries_input.setPlaceholderText(f"{DEFAULT_MAX_RETRIES} (پیش‌فرض)")
        self.retries_input.setToolTip(
            "تعداد تلاش دوباره خودکار در برابر خطاهای موقت سرویس."
        )
        self._add_form_row(form_layout, "تلاش دوباره", self.retries_input)

        self.temperature_input = QLineEdit()
        self.temperature_input.setObjectName("settingsInput")
        self._configure_input(self.temperature_input)
        self.temperature_input.setPlaceholderText(f"{DEFAULT_TEMPERATURE:g} (پیش‌فرض)")
        self.temperature_input.setToolTip(
            "مقدار کمتر پاسخ‌های ثابت‌تر و مقدار بیشتر پاسخ‌های متنوع‌تر می‌سازد."
        )
        self._add_form_row(form_layout, "تنوع پاسخ", self.temperature_input)

        # فرم نباید برای جا شدن در پنجره، فاصله ردیف‌ها را حذف یا ردیف‌ها را فشرده کند.
        form.setMinimumHeight(6 * 44 + 5 * 14)
        frame_layout.addWidget(form)

        buttons = QWidget()
        buttons_layout = QHBoxLayout(buttons)
        buttons_layout.setContentsMargins(0, 0, 0, 0)
        buttons_layout.setSpacing(10)

        self.save_button = QPushButton("ذخیره")
        self.save_button.setObjectName("primaryButton")
        self.save_button.setFixedHeight(36)
        self.save_button.clicked.connect(self.save)

        self.test_button = QPushButton("تست اتصال")
        self.test_button.setObjectName("ghostButton")
        self.test_button.setFixedHeight(36)
        self.test_button.setToolTip(
            "مقادیر همین فرم (حتی ذخیره‌نشده) آزمایش می‌شوند و چیزی ذخیره نمی‌شود."
        )
        self.test_button.clicked.connect(self.test_connection)

        buttons_layout.addWidget(self.save_button)
        buttons_layout.addWidget(self.test_button)
        buttons_layout.addStretch(1)
        frame_layout.addWidget(buttons)

        self.status_label = QLabel()
        self.status_label.setObjectName("settingsStatus")
        self.status_label.setWordWrap(True)
        frame_layout.addWidget(self.status_label)

        return frame

    def _create_theme_row(self) -> QWidget:
        """ردیف انتخاب ظاهر برنامه (تیره/روشن) با اثر فوری."""
        row = QWidget()
        row.setObjectName("themeRow")
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(10)

        caption = QLabel("ظاهر برنامه")
        caption.setObjectName("panelHeading")
        row_layout.addWidget(caption)

        self.theme_combo = QComboBox()
        self.theme_combo.setObjectName("settingsInput")
        self.theme_combo.setFixedHeight(36)
        self.theme_combo.addItem("تیره", THEME_DARK)
        self.theme_combo.addItem("روشن", THEME_LIGHT)
        self.theme_combo.setToolTip("بلافاصله اعمال و برای اجراهای بعدی ذخیره می‌شود.")
        self.theme_combo.currentIndexChanged.connect(self._on_theme_selected)
        row_layout.addWidget(self.theme_combo)
        row_layout.addStretch(1)

        return row

    def _create_data_frame(self) -> QFrame:
        """کادر پشتیبان‌گیری و بازیابی داده‌های برنامه."""
        frame = QFrame()
        frame.setObjectName("settingsFrame")
        frame.setMaximumWidth(640)

        layout = QVBoxLayout(frame)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)

        heading = QLabel("داده‌ها")
        heading.setObjectName("panelHeading")
        layout.addWidget(heading)

        description = QLabel(
            "همه گفتگوها، یادداشت‌ها، وظایف و حافظه‌ها در یک فایل JSON پشتیبان‌گیری "
            "می‌شوند. بازیابی، داده‌های فعلی را با محتوای فایل جایگزین می‌کند."
        )
        description.setObjectName("pageDescription")
        description.setWordWrap(True)
        layout.addWidget(description)

        hint = QLabel(
            "هنگام بستن برنامه هم یک پشتیبان خودکار ساخته می‌شود و فقط ۵ نسخه آخر "
            f"در {self._backup_folder_text()} نگه داشته می‌شود."
        )
        hint.setObjectName("settingsHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        buttons = QWidget()
        buttons_layout = QHBoxLayout(buttons)
        buttons_layout.setContentsMargins(0, 0, 0, 0)
        buttons_layout.setSpacing(10)

        self.backup_button = QPushButton("پشتیبان‌گیری…")
        self.backup_button.setObjectName("ghostButton")
        self.backup_button.setFixedHeight(34)
        self.backup_button.clicked.connect(self.choose_export_path)

        self.restore_button = QPushButton("بازیابی…")
        self.restore_button.setObjectName("ghostButton")
        self.restore_button.setFixedHeight(34)
        self.restore_button.clicked.connect(self.choose_restore_path)

        buttons_layout.addWidget(self.backup_button)
        buttons_layout.addWidget(self.restore_button)
        buttons_layout.addStretch(1)
        layout.addWidget(buttons)

        self.data_status_label = QLabel()
        self.data_status_label.setObjectName("settingsStatus")
        self.data_status_label.setWordWrap(True)
        layout.addWidget(self.data_status_label)

        return frame

    # --------------------------------------------------------------------- رفتار

    def reload(self) -> None:
        """مقادیر فعلی تنظیمات را در فرم نشان می‌دهد."""
        self._settings.reload()
        self.api_key_input.setText(self._settings.api_key)
        self.model_input.setText(
            "" if self._settings.model == AppSettings.DEFAULT_MODEL else self._settings.model
        )
        self.base_url_input.setText(self._settings.base_url)
        self.timeout_input.setText(self._non_default(self._settings.request_timeout, DEFAULT_TIMEOUT_SECONDS))
        self.retries_input.setText(self._non_default(self._settings.max_retries, DEFAULT_MAX_RETRIES))
        self.temperature_input.setText(
            self._non_default(self._settings.temperature, DEFAULT_TEMPERATURE)
        )
        self.set_theme_value(self.active_theme())
        self._set_status()
        self._set_data_status()

    # ------------------------------------------------------------------- ظاهر

    def active_theme(self) -> str:
        """تم فعلی برنامه؛ از پنجره اصلی می‌پرسد و پیش‌فرض تیره است."""
        window = self.window()
        return getattr(window, "current_theme", THEME_DARK)

    def set_theme_value(self, theme: str) -> None:
        """کمبوی تم را بدون صدور سیگنال، با مقدار داده‌شده همگام می‌کند."""
        normalised = normalise_theme(theme)
        index = self.theme_combo.findData(normalised)
        if index >= 0 and index != self.theme_combo.currentIndex():
            self.theme_combo.blockSignals(True)
            self.theme_combo.setCurrentIndex(index)
            self.theme_combo.blockSignals(False)

    def _on_theme_selected(self) -> None:
        """انتخاب تازه کاربر را اعلام می‌کند؛ اعمالش کار پنجره اصلی است."""
        theme = self.theme_combo.currentData()
        if theme:
            self.theme_changed.emit(theme)

    def _non_default(self, value: float | int, default: float | int) -> str:
        """مقدار را فقط وقتی نشان می‌دهد که با پیش‌فرض تفاوت داشته باشد.

        کادر خالی با متن راهنما (placeholder) یعنی «همان پیش‌فرض»؛ اینطور کاربر
        می‌داند چه چیزی واقعاً در فایل .env نوشته شده است.
        """
        if float(value) == float(default):
            return ""

        return f"{value:g}"

    def collect_values(self) -> dict[str, str]:
        """مقادیر فرم را با اعتبارسنجی برمی‌گرداند.

        در صورت نامعتبر بودن یکی از اعداد، `ValueError` با پیام فارسی پرتاب می‌شود تا
        مقدار اشتباه در `.env` نوشته نشود و کاربر بداند مشکل کجاست.
        """
        values = {
            "OPENAI_API_KEY": self.api_key_input.text(),
            "OPENAI_MODEL": self.model_input.text(),
            "OPENAI_BASE_URL": self.base_url_input.text(),
            "OPENAI_TIMEOUT": "",
            "OPENAI_MAX_RETRIES": "",
            "OPENAI_TEMPERATURE": "",
        }

        timeout_text = self.timeout_input.text().strip()
        if timeout_text:
            try:
                seconds = float(timeout_text)
            except ValueError:
                raise ValueError("زمان انتظار باید یک عدد بر حسب ثانیه باشد.") from None

            if not MIN_TIMEOUT_SECONDS <= seconds <= MAX_TIMEOUT_SECONDS:
                raise ValueError(
                    f"زمان انتظار باید بین {MIN_TIMEOUT_SECONDS:g} و "
                    f"{MAX_TIMEOUT_SECONDS:g} ثانیه باشد."
                )

            values["OPENAI_TIMEOUT"] = f"{seconds:g}"

        retries_text = self.retries_input.text().strip()
        if retries_text:
            try:
                retries = int(retries_text)
            except ValueError:
                raise ValueError("تعداد تلاش دوباره باید یک عدد درست باشد.") from None

            if not 0 <= retries <= MAX_RETRIES_LIMIT:
                raise ValueError(
                    f"تعداد تلاش دوباره باید بین ۰ و {MAX_RETRIES_LIMIT} باشد."
                )

            values["OPENAI_MAX_RETRIES"] = str(retries)

        temperature_text = self.temperature_input.text().strip()
        if temperature_text:
            try:
                temperature = float(temperature_text)
            except ValueError:
                raise ValueError("تنوع پاسخ باید یک عدد باشد.") from None

            if not MIN_TEMPERATURE <= temperature <= MAX_TEMPERATURE:
                raise ValueError(
                    f"تنوع پاسخ باید بین {MIN_TEMPERATURE:g} و "
                    f"{MAX_TEMPERATURE:g} باشد."
                )

            values["OPENAI_TEMPERATURE"] = f"{temperature:g}"

        return values

    def save(self) -> None:
        """فرم را در فایل .env ذخیره می‌کند و نتیجه را گزارش می‌کند."""
        try:
            values = self.collect_values()
        except ValueError as error:
            self._set_status(str(error), error=True)
            return

        try:
            self._settings.save(**values)
        except (OSError, ValueError) as error:
            self._set_status(f"ذخیره‌سازی ناموفق بود: {error}", error=True)
            return

        self._set_status("تنظیمات ذخیره شد.")
        self.saved.emit()

    # ------------------------------------------------------------ تست اتصال

    def test_connection(self) -> None:
        """اتصال را با مقادیر همین فرم (حتی ذخیره‌نشده) بررسی می‌کند.

        بررسی در رشته‌ای جدا انجام می‌شود تا پنجره در مدت انتظار پاسخ‌گو بماند، و
        نتیجه فقط به صفحه گزارش می‌شود؛ چیزی در `.env` نوشته نمی‌شود.
        """
        if self._test_worker is not None:
            return

        try:
            overrides = self.collect_values()
        except ValueError as error:
            self._set_status(str(error), error=True)
            return

        preview = self._settings.with_overrides(**overrides)
        worker = ConnectionTestWorker(ChatService(preview))
        worker.succeeded.connect(self._on_test_succeeded)
        worker.failed.connect(self._on_test_failed)
        worker.finished.connect(self._on_test_finished)

        self._test_worker = worker
        self.test_button.setEnabled(False)
        self.test_button.setText("در حال بررسی…")
        self._set_status("در حال بررسی اتصال…")
        worker.start()

    def _on_test_succeeded(self, message: str) -> None:
        """نتیجه موفق تست اتصال را نشان می‌دهد."""
        self._set_status(message)

    def _on_test_failed(self, message: str) -> None:
        """نتیجه ناموفق تست اتصال را نشان می‌دهد."""
        self._set_status(message, error=True)

    def _on_test_finished(self) -> None:
        """دکمه تست را به حالت عادی برمی‌گرداند و مرجع رشته را آزاد می‌کند.

        شیء QThread پس از پایان کامل رشته آزاد می‌شود؛ تخریب آن در حالی که رشته
        هنوز تمام نشده، باعث کرش سطح پایین Qt می‌شود.
        """
        self._test_worker = None
        self.test_button.setEnabled(True)
        self.test_button.setText("تست اتصال")

    def shutdown(self) -> None:
        """منتظر پایان تست اتصال در حال اجرا می‌ماند تا بستن برنامه امن باشد."""
        worker = self._test_worker
        if worker is None:
            return

        worker.wait(5000)
        self._test_worker = None

    # ---------------------------------------------------- پشتیبان‌گیری و بازیابی

    def choose_export_path(self) -> None:
        """از کاربر مسیر فایل پشتیبان را می‌گیرد و داده‌ها را ذخیره می‌کند."""
        path, _ = QFileDialog.getSaveFileName(
            self,
            "ذخیره پشتیبان",
            default_backup_name(),
            "JSON (*.json)",
        )

        if path:
            self.export_to(path)

    def export_to(self, path: str | Path) -> bool:
        """داده‌های برنامه را در مسیر داده‌شده ذخیره می‌کند."""
        if self._store is None:
            self._set_data_status("پشتیبان‌گیری در دسترس نیست.", error=True)
            return False

        try:
            backup_path = export_backup(self._store, path)
            tables = read_backup(backup_path)
        except BackupError as error:
            self._set_data_status(str(error), error=True)
            return False

        self._set_data_status(
            f"پشتیبان ساخته شد: {backup_path.name} ({summarise(tables)})"
        )

        return True

    def choose_restore_path(self) -> None:
        """فایل پشتیبان را از کاربر می‌گیرد، خلاصه را نشان می‌دهد و بازیابی می‌کند."""
        path, _ = QFileDialog.getOpenFileName(self, "انتخاب فایل پشتیبان", "", "JSON (*.json)")

        if path:
            self.restore_from(path, ask_confirmation=True)

    def restore_from(self, path: str | Path, *, ask_confirmation: bool = False) -> bool:
        """داده‌ها را از فایل پشتیبان بازمی‌گرداند.

        پیش از بازنویسی، خلاصه محتوای فایل به کاربر نشان داده می‌شود تا بدون
        تأیید، داده‌های فعلی جایگزین نشوند.
        """
        if self._store is None:
            self._set_data_status("بازیابی در دسترس نیست.", error=True)
            return False

        try:
            tables = read_backup(path)
        except BackupError as error:
            self._set_data_status(str(error), error=True)
            return False

        if ask_confirmation:
            answer = QMessageBox.question(
                self,
                "بازیابی پشتیبان",
                "این فایل شامل "
                f"{summarise(tables)} است.\n"
                "داده‌های فعلی جایگزین و گفتگوی باز پاک می‌شوند. ادامه می‌دهید؟",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )

            if answer != QMessageBox.StandardButton.Yes:
                self._set_data_status("بازیابی لغو شد.")
                return False

        try:
            counts = import_backup(self._store, path)
        except BackupError as error:
            self._set_data_status(str(error), error=True)
            return False

        restored = "، ".join(
            f"{count} {TABLE_LABELS[table]}" for table, count in counts.items() if count
        )
        self._set_data_status(f"بازیابی انجام شد: {restored or 'بدون داده'}")
        self.data_restored.emit()

        return True

    def _backup_folder_text(self) -> str:
        """مسیر پوشه پشتیبان‌های خودکار برای نمایش در صفحه."""
        folder = default_backup_folder(self._store)

        # مسیرهای طولانی نوار را به‌هم نریزند؛ نام پوشه کافی است.
        return folder.name if len(str(folder)) > 48 else str(folder)

    def _set_data_status(self, text: str | None = None, error: bool = False) -> None:
        """پیام وضعیت بخش داده‌ها را جایگزین می‌کند."""
        if text is None:
            text = (
                "آماده است؛ پشتیبان‌گیری فقط خواندنی است و چیزی را تغییر نمی‌دهد."
                if self._store is not None
                else "پایگاه‌داده در دسترس نیست."
            )

        self.data_status_label.setText(text)
        self.data_status_label.setProperty("error", "true" if error else "false")
        style = self.data_status_label.style()
        style.unpolish(self.data_status_label)
        style.polish(self.data_status_label)

    def _set_status(self, text: str | None = None, error: bool = False) -> None:
        """پیام وضعیت زیر فرم را جایگزین می‌کند."""
        if text is None:
            text = (
                "آماده است."
                if self._settings.is_configured
                else "کلید API تنظیم نشده است؛ گفتگو غیرفعال خواهد ماند."
            )

        self.status_label.setText(text)
        self.status_label.setProperty("error", "true" if error else "false")
        style = self.status_label.style()
        style.unpolish(self.status_label)
        style.polish(self.status_label)
