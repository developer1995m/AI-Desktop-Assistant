"""لایه ارتباط با سرویس هوش مصنوعی برای صفحه گفتگو."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
import re
from typing import Any
from urllib.parse import urlparse

import sqlite3

from openai import OpenAI

from app.services.settings import AppSettings
from app.services.storage import ConversationStore

SYSTEM_PROMPT = (
    "You are AI Desktop Assistant, a concise and helpful desktop assistant. "
    "Answer in the same language the user writes in, keep answers practical, "
    "and prefer short paragraphs or bullet lists over long walls of text."
)

MAX_HISTORY_MESSAGES = 20
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1", "0.0.0.0"}
MEMORY_HEADER = (
    "Things you permanently know about the user "
    "(use them silently when relevant, do not recite them):"
)


class ChatServiceError(Exception):
    """خطای پایه در ارتباط با سرویس گفتگو."""


class MissingApiKeyError(ChatServiceError):
    """کلید API تنظیم نشده است و امکان ارسال درخواست وجود ندارد."""


def _redact_sensitive_detail(detail: str) -> str:
    """نشانه‌های رایج credential را از جزئیات خطا حذف می‌کند."""
    patterns = (
        (r"(?i)(authorization\s*:\s*)[^\s,;]+", r"\1[REDACTED]"),
        (r"(?i)\bbearer\s+[^\s,;]+", "Bearer [REDACTED]"),
        (r"(?i)\bsk-[A-Za-z0-9_-]+", "[REDACTED_API_KEY]"),
        (r"(?i)(OPENAI_API_KEY\s*[=:]\s*)[^\s,;]+", r"\1[REDACTED]"),
        (r"(?i)(api[_ -]?key\s*[=:]\s*)[^\s,;]+", r"\1[REDACTED]"),
    )
    redacted = detail
    for pattern, replacement in patterns:
        redacted = re.sub(pattern, replacement, redacted)
    return redacted


def describe_error(error: BaseException) -> str:
    """خطای ارتباط با سرویس را به پیام فارسی قابل‌فهم تبدیل می‌کند.

    دسته‌بندی بر پایه کد وضعیت و نام کلاس خطاست، نه نوع‌های خود کتابخانه؛ اینطور با
    هر نسخه‌ای از کلاینت سازگار با OpenAI و با کلاینت‌های آزمایشی هم درست کار می‌کند.
    """
    if isinstance(error, ChatServiceError):
        return _redact_sensitive_detail(str(error))

    name = type(error).__name__
    status = getattr(error, "status_code", None)
    if status in {401, 403} or "Authentication" in name or "PermissionDenied" in name:
        return "کلید API پذیرفته نشد؛ مقدار OPENAI_API_KEY را در صفحه تنظیمات بررسی کنید."
    if status == 404 or "NotFound" in name:
        return "مدل یا Base URL پیدا نشد؛ نام مدل و آدرس سرویس را در تنظیمات بررسی کنید."
    if status == 429 or "RateLimit" in name:
        return "سهمیه یا محدودیت نرخ سرویس پر شده است؛ چند لحظه بعد دوباره تلاش کنید."
    if isinstance(status, int) and status >= 500:
        return "سرویس هوش مصنوعی موقتاً در دسترس نیست؛ کمی بعد دوباره تلاش کنید."
    # کلاس Timeout در کتابخانه از کلاس خطای اتصال ارث می‌برد، پس اول بررسی می‌شود.
    if "Timeout" in name:
        return (
            "پاسخ سرویس در زمان مقرر نرسید؛ اتصال اینترنت یا مقدار زمان انتظار در "
            "تنظیمات را بررسی کنید."
        )
    if "Connection" in name or isinstance(error, (OSError, TimeoutError)):
        return "اتصال به اینترنت یا سرویس برقرار نشد؛ اتصال شبکه را بررسی کنید."
    if status == 400 or "BadRequest" in name:
        return "درخواست پذیرفته نشد؛ تنظیمات مدل را بررسی کنید."

    return f"خطای پیش‌بینی‌نشده در ارتباط با مدل: {name}"


def is_local_base_url(base_url: str) -> bool:
    """آیا آدرس سرویس به خود همین رایانه اشاره می‌کند؟"""
    if not base_url:
        return False

    host = (urlparse(base_url).hostname or "").lower()

    return host.strip("[]") in LOOPBACK_HOSTS


def _local_http_client(base_url: str, timeout: float) -> Any | None:
    """کلاینت HTTP بدون پروکسی برای سرویس‌های محلی می‌سازد.

    کتابخانه HTTP پشت SDK، پروکسی سیستم را از محیط می‌خواند و آن را برای **همه**
    نشانی‌ها از جمله `localhost` به کار می‌برد. اگر کاربر مدل محلی (Ollama،
    LM Studio و مانند آن) را در Base URL گذاشته باشد و روی سیستم هم یک پروکسی یا
    VPN روشن باشد، درخواست به پروکسی می‌رود و با ۵۰۳ برمی‌گردد. برای نشانی محلی
    پروکسی را کنار می‌گذاریم؛ خود ویندوز هم localhost را به‌صورت پیش‌فرض مستثنا می‌کند.
    """
    if not is_local_base_url(base_url):
        return None

    try:
        import httpx2
    except ImportError:  # pragma: no cover - فقط اگر کتابخانه پشت SDK عوض شود
        return None

    return httpx2.Client(timeout=timeout, trust_env=False)


def build_messages(
    history: Sequence[dict[str, Any]],
    prompt: str,
    *,
    system_prompt: str = SYSTEM_PROMPT,
    memories: Sequence[str] = (),
    max_history: int = MAX_HISTORY_MESSAGES,
) -> list[dict[str, str]]:
    """پیام‌های ارسالی به مدل را از تاریخچه گفتگو، حافظه و پیام جدید می‌سازد."""
    system_content = system_prompt
    active_memories = [memory for memory in memories if memory and memory.strip()]

    if active_memories:
        memory_lines = "\n".join(f"- {memory}" for memory in active_memories)
        system_content = f"{system_prompt}\n\n{MEMORY_HEADER}\n{memory_lines}"

    messages: list[dict[str, str]] = [{"role": "system", "content": system_content}]

    for message in list(history)[-max_history:]:
        role = message.get("role")
        content = message.get("content")

        if role not in {"user", "assistant"} or not content:
            continue

        messages.append({"role": role, "content": str(content)})

    messages.append({"role": "user", "content": prompt})
    return messages


class ChatService:
    """ارسال پیام کاربر به مدل و دریافت پاسخ به صورت جریانی (streaming)."""

    def __init__(self, settings: AppSettings, store: ConversationStore | None = None) -> None:
        self._settings = settings
        self._store = store

    @property
    def model(self) -> str:
        """نام مدل فعال در تنظیمات."""
        return self._settings.model

    def is_configured(self) -> bool:
        """آیا امکان ارسال درخواست به مدل وجود دارد؟"""
        return self._settings.is_configured

    def reload_configuration(self) -> None:
        """تنظیمات را دوباره از فایل .env می‌خواند تا تغییرات بدون اجرای مجدد اعمال شود."""
        self._settings.reload()

    def active_memories(self) -> list[str]:
        """متن حافظه‌های فعال را برای تزریق در پرامپت برمی‌گرداند.

        این متد باید در رشته رابط کاربری صدا زده شود؛ اتصال SQLite بین رشته‌ها
        قابل استفاده نیست، پس نتیجه پیش از شروع درخواست خوانده می‌شود و به
        `stream_reply` پاس داده می‌شود.
        """
        if self._store is None:
            return []

        try:
            return [memory.content for memory in self._store.list_memories(only_enabled=True)]
        except sqlite3.Error:
            return []

    def stream_reply(
        self,
        history: Sequence[dict[str, Any]],
        prompt: str,
        *,
        should_stop: Callable[[], bool] | None = None,
        memories: Sequence[str] | None = None,
        system_prompt: str | None = None,
    ) -> Iterator[str]:
        """پاسخ مدل را به صورت تکه‌های متنی تولید می‌کند.

        `should_stop` امکان لغو درخواست توسط کاربر را فراهم می‌کند، `memories`
        فهرست حافظه‌های از پیش خوانده‌شده است (وقتی None باشد از پایگاه‌داده خوانده
        می‌شود) و `system_prompt` امکان استفاده از پرامپت اختصاصی (مثلاً پرسش از
        یک سند PDF) را می‌دهد.
        """
        if not self.is_configured():
            raise MissingApiKeyError(
                "کلید API تنظیم نشده است. مقدار OPENAI_API_KEY را در فایل .env وارد کنید."
            )

        active_memories = self.active_memories() if memories is None else list(memories)

        client = self._create_client()
        stream = client.chat.completions.create(
            model=self.model,
            messages=build_messages(
                history,
                prompt,
                system_prompt=system_prompt or SYSTEM_PROMPT,
                memories=active_memories,
            ),
            temperature=self._settings.temperature,
            stream=True,
        )

        try:
            for chunk in stream:
                if should_stop is not None and should_stop():
                    break

                if not chunk.choices:
                    continue

                content = getattr(chunk.choices[0].delta, "content", None)
                if content:
                    yield content
        finally:
            stream.close()

    def check_connection(self) -> str:
        """یک درخواست کوچک می‌فرستد تا کلید، آدرس و نام مدل بررسی شود.

        در صورت موفقیت پیام کوتاهی برمی‌گرداند و در غیر این صورت
        `ChatServiceError` با پیام فارسی قابل نمایش پرتاب می‌کند.
        """
        if not self.is_configured():
            raise MissingApiKeyError(
                "کلید API تنظیم نشده است. مقدار OPENAI_API_KEY را در فایل .env وارد کنید."
            )

        try:
            client = self._create_client()
            client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=1,
            )
        except Exception as error:  # noqa: BLE001 - همه خطاها به پیام کاربر تبدیل می‌شوند
            raise ChatServiceError(describe_error(error)) from error

        return f"اتصال برقرار است — مدل «{self.model}» پاسخ داد."

    def _client_options(self) -> dict[str, Any]:
        """گزینه‌های ساخت کلاینت را از تنظیمات فعلی می‌سازد."""
        timeout = self._settings.request_timeout
        options: dict[str, Any] = {
            "api_key": self._settings.api_key,
            "timeout": timeout,
            "max_retries": self._settings.max_retries,
        }

        if self._settings.base_url:
            options["base_url"] = self._settings.base_url

        local_client = _local_http_client(self._settings.base_url, timeout)
        if local_client is not None:
            options["http_client"] = local_client

        return options

    def _create_client(self) -> OpenAI:
        """کلاینت OpenAI را با تنظیمات فعلی می‌سازد."""
        return OpenAI(**self._client_options())
