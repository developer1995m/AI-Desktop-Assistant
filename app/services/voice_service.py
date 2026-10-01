"""تبدیل فایل صوتی به متن با API گفتاری OpenAI-compatible."""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from openai import OpenAI

from app.services.chat_service import MissingApiKeyError, _local_http_client, describe_error
from app.services.settings import AppSettings


class VoiceServiceError(Exception):
    """خطای تبدیل صدا به متن."""


class VoiceService:
    """تبدیل فایل‌های صوتی به متن با API تشخیص صدا."""

    DEFAULT_MODEL = "whisper-1"

    def __init__(self, settings: AppSettings) -> None:
        self._settings = settings

    def is_configured(self) -> bool:
        """آیا کلید API برای تشخیص صدا تنظیم شده است؟"""
        return self._settings.is_configured

    def transcribe_file(self, path: str | Path) -> str:
        """متن یک فایل صوتی را برمی‌گرداند."""
        if not self.is_configured():
            raise MissingApiKeyError(
                "کلید API تنظیم نشده است. مقدار OPENAI_API_KEY را در فایل .env وارد کنید."
            )

        file_path = Path(path)
        if not file_path.is_file():
            raise VoiceServiceError(f"فایل صوتی پیدا نشد: {file_path}")

        try:
            mime_type = self._mime_type_for(file_path)
            client = OpenAI(**self._client_options())
            if self._uses_gemini_audio_endpoint():
                encoded_audio = base64.b64encode(file_path.read_bytes()).decode("ascii")
                result = client.chat.completions.create(
                    model=self._settings.model,
                    messages=[
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "text",
                                    "text": (
                                        "Transcribe the speech in this audio as Persian (Farsi). "
                                        "Write the transcript in Persian script, not Devanagari. "
                                        "Return only the transcript; do not translate it."
                                    ),
                                },
                                {
                                    "type": "input_audio",
                                    "input_audio": {
                                        "data": encoded_audio,
                                        "format": file_path.suffix.lower().lstrip("."),
                                    },
                                },
                            ],
                        }
                    ],
                )
                text = result.choices[0].message.content
            else:
                with file_path.open("rb") as audio_file:
                    result = client.audio.transcriptions.create(
                        model=self.DEFAULT_MODEL,
                        file=(file_path.name, audio_file, mime_type),
                    )

                text = getattr(result, "text", None)
                if text is None:
                    text = str(result)

            cleaned = str(text).strip()
            if not cleaned:
                raise VoiceServiceError("فایل صوتی خالی بود یا متن تشخیص داده نشد.")

            return cleaned
        except Exception as error:  # noqa: BLE001 - پیام کاربر باید قابل‌خواندن باشد.
            if isinstance(error, (MissingApiKeyError, VoiceServiceError)):
                raise
            raise VoiceServiceError(describe_error(error)) from error

    def _mime_type_for(self, path: Path) -> str:
        """نوع MIME فایل صوتی را از نام پرونده حدس می‌زند."""
        suffix = path.suffix.lower()
        mapping = {
            ".wav": "audio/wav",
            ".mp3": "audio/mpeg",
            ".m4a": "audio/mp4",
            ".aac": "audio/aac",
            ".ogg": "audio/ogg",
            ".flac": "audio/flac",
        }
        return mapping.get(suffix, "application/octet-stream")

    def _uses_gemini_audio_endpoint(self) -> bool:
        """آیا Base URL به endpoint سازگار Gemini اشاره می‌کند؟"""
        return (
            urlparse(self._settings.base_url).hostname or ""
        ).lower() == "generativelanguage.googleapis.com"

    def _client_options(self) -> dict[str, Any]:
        """گزینه‌های ساخت کلاینت OpenAI را برمی‌سازد."""
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
