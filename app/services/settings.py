"""مدیریت تنظیمات برنامه و کلیدهای دسترسی سرویس هوش مصنوعی."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import dotenv_values

from app.services.paths import env_path as default_env_path

DEFAULT_ENV_PATH = default_env_path()

KNOWN_VARIABLES = (
    "OPENAI_API_KEY",
    "OPENAI_MODEL",
    "OPENAI_BASE_URL",
    "OPENAI_TIMEOUT",
    "OPENAI_MAX_RETRIES",
    "OPENAI_TEMPERATURE",
)

# زمان انتظار پیش‌فرض هر درخواست؛ پیش‌فرض خود کتابخانه ۶۰۰ ثانیه است که برای
# کاربر پشت پنجره یعنی انتظاری طولانی و بی‌توضیح.
DEFAULT_TIMEOUT_SECONDS = 60.0
MIN_TIMEOUT_SECONDS = 5.0
MAX_TIMEOUT_SECONDS = 600.0
DEFAULT_MAX_RETRIES = 2
MAX_RETRIES_LIMIT = 5
DEFAULT_TEMPERATURE = 0.7
MIN_TEMPERATURE = 0.0
MAX_TEMPERATURE = 2.0


class AppSettings:
    """تنظیمات برنامه را از متغیرهای محیطی و فایل .env می‌خواند.

    اولویت خواندن مقادیر: متغیر محیطی سیستم، سپس فایل `.env`، سپس مقدار پیش‌فرض.
    """

    API_KEY_VARIABLE = "OPENAI_API_KEY"
    MODEL_VARIABLE = "OPENAI_MODEL"
    BASE_URL_VARIABLE = "OPENAI_BASE_URL"
    TIMEOUT_VARIABLE = "OPENAI_TIMEOUT"
    RETRIES_VARIABLE = "OPENAI_MAX_RETRIES"
    TEMPERATURE_VARIABLE = "OPENAI_TEMPERATURE"
    DEFAULT_MODEL = "gpt-4o-mini"
    DEFAULT_TIMEOUT = DEFAULT_TIMEOUT_SECONDS
    DEFAULT_RETRIES = DEFAULT_MAX_RETRIES
    DEFAULT_TEMPERATURE = DEFAULT_TEMPERATURE

    def __init__(self, env_path: Path | str | None = None) -> None:
        self.env_path = Path(env_path) if env_path is not None else DEFAULT_ENV_PATH
        self._file_values: dict[str, str] = {}
        self.reload()

    def reload(self) -> None:
        """فایل .env را دوباره می‌خواند تا تغییرات بدون اجرای مجدد برنامه اعمال شوند."""
        if self.env_path.is_file():
            self._file_values = {
                key: value
                for key, value in dotenv_values(self.env_path).items()
                if value is not None
            }
        else:
            self._file_values = {}

    def _value(self, variable: str) -> str:
        """مقدار یک متغیر را با در نظر گرفتن اولویت محیط سیستم برمی‌گرداند."""
        from_environment = os.environ.get(variable)
        if from_environment and from_environment.strip():
            return from_environment.strip()

        return (self._file_values.get(variable) or "").strip()

    @property
    def api_key(self) -> str:
        """کلید API سرویس گفتگو."""
        return self._value(self.API_KEY_VARIABLE)

    @property
    def model(self) -> str:
        """نام مدلی که در گفتگو استفاده می‌شود."""
        return self._value(self.MODEL_VARIABLE) or self.DEFAULT_MODEL

    @property
    def base_url(self) -> str:
        """آدرس سرویس سازگار با OpenAI در صورت استفاده از پروکسی یا سرویس جایگزین."""
        return self._value(self.BASE_URL_VARIABLE)

    @property
    def request_timeout(self) -> float:
        """زمان انتظار هر درخواست به سرویس (ثانیه).

        مقدار نامعتبر یا خارج از بازه مجاز نادیده گرفته می‌شود تا یک عدد اشتباه در
        `.env` برنامه را غیرقابل استفاده نکند.
        """
        raw = self._value(self.TIMEOUT_VARIABLE)

        try:
            seconds = float(raw)
        except ValueError:
            return DEFAULT_TIMEOUT_SECONDS

        if not MIN_TIMEOUT_SECONDS <= seconds <= MAX_TIMEOUT_SECONDS:
            return DEFAULT_TIMEOUT_SECONDS

        return seconds

    @property
    def max_retries(self) -> int:
        """تعداد تلاش دوباره در برابر خطاهای موقت سرویس."""
        raw = self._value(self.RETRIES_VARIABLE)

        try:
            retries = int(raw)
        except ValueError:
            return DEFAULT_MAX_RETRIES

        return max(0, min(MAX_RETRIES_LIMIT, retries))

    @property
    def temperature(self) -> float:
        """میزان تصادفی‌بودن پاسخ مدل را برمی‌گرداند."""
        raw = self._value(self.TEMPERATURE_VARIABLE)

        try:
            temperature = float(raw)
        except ValueError:
            return DEFAULT_TEMPERATURE

        if not MIN_TEMPERATURE <= temperature <= MAX_TEMPERATURE:
            return DEFAULT_TEMPERATURE

        return temperature

    @property
    def is_configured(self) -> bool:
        """آیا کلید API برای برقراری ارتباط با مدل تنظیم شده است؟"""
        return bool(self.api_key)

    def with_overrides(self, **values: str) -> AppSettings:
        """نسخه موقتی از تنظیمات می‌سازد که مقادیر داده‌شده را جای مقادیر ذخیره‌شده دارد.

        برای آزمودن مقادیر فرم پیش از ذخیره‌کردن استفاده می‌شود و **هیچ چیزی روی دیسک
        نمی‌نویسد**. اولویت متغیر محیطی سیستم در این نسخه هم مثل نسخه اصلی رعایت می‌شود.
        """
        for variable in values:
            if variable not in KNOWN_VARIABLES:
                raise ValueError(f"متغیر ناشناخته: {variable}")

        clone = AppSettings(self.env_path)
        clone._file_values = dict(self._file_values)

        for variable, raw in values.items():
            value = raw.strip()
            if value:
                clone._file_values[variable] = value
            else:
                clone._file_values.pop(variable, None)

        return clone

    def save(self, **values: str) -> None:
        """مقادیر داده‌شده را در فایل .env می‌نویسد.

        متغیرهای شناخته‌شده همیشه در ابتدای فایل و مرتب می‌آیند و هر خط دیگری
        که کاربر خودش به فایل اضافه کرده باشد دست‌نخورده باقی می‌ماند. مقدار
        رشته خالی یعنی حذف متغیر.
        """
        file_values = dict(self._file_values)

        for variable, raw in values.items():
            if variable not in KNOWN_VARIABLES:
                raise ValueError(f"متغیر ناشناخته: {variable}")

            value = raw.strip()
            if value:
                file_values[variable] = value
            else:
                file_values.pop(variable, None)

        known_lines = [
            f"{variable}={file_values[variable]}"
            for variable in KNOWN_VARIABLES
            if variable in file_values
        ]
        extra_lines = [
            line
            for line in self._read_env_lines()
            if line and not line.lstrip().startswith(KNOWN_VARIABLES)
        ]

        content = "\n".join([*known_lines, *extra_lines, ""])

        if self.env_path.parent != Path(""):
            self.env_path.parent.mkdir(parents=True, exist_ok=True)

        self.env_path.write_text(content, encoding="utf-8")
        self.reload()

    def _read_env_lines(self) -> list[str]:
        """خط‌های فعلی فایل .env را به‌صورت متن خام برمی‌گرداند."""
        if not self.env_path.is_file():
            return []

        lines = self.env_path.read_text(encoding="utf-8").splitlines()

        # خط‌های خالی انتهای فایل در ذخیره‌سازی دوباره ساخته می‌شوند.
        while lines and not lines[-1].strip():
            lines.pop()

        return lines
