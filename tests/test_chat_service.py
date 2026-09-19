"""تست‌های لایه تنظیمات و سرویس گفتگو."""

import time
from types import SimpleNamespace

import pytest

from app.services.chat_service import ChatService, MissingApiKeyError, build_messages
from app.services.settings import AppSettings


def write_env(tmp_path, content: str):
    """یک فایل .env موقت می‌سازد و مسیر آن را برمی‌گرداند."""
    env_path = tmp_path / ".env"
    env_path.write_text(content, encoding="utf-8")
    return env_path


def test_settings_defaults_when_env_missing(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)

    settings = AppSettings(tmp_path / "missing.env")

    assert settings.api_key == ""
    assert settings.model == AppSettings.DEFAULT_MODEL
    assert settings.base_url == ""
    assert settings.is_configured is False


def test_settings_reads_values_and_environment_wins(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    env_path = write_env(
        tmp_path,
        "OPENAI_API_KEY=file-key\nOPENAI_MODEL=file-model\nOPENAI_BASE_URL=https://example.test/v1\n",
    )

    settings = AppSettings(env_path)
    assert settings.api_key == "file-key"
    assert settings.model == "file-model"
    assert settings.base_url == "https://example.test/v1"
    assert settings.is_configured is True

    monkeypatch.setenv("OPENAI_API_KEY", "environment-key")
    assert settings.api_key == "environment-key"


def test_settings_reload_picks_up_new_values(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    env_path = write_env(tmp_path, "OPENAI_API_KEY=\n")

    settings = AppSettings(env_path)
    assert settings.is_configured is False

    env_path.write_text("OPENAI_API_KEY=later-key\n", encoding="utf-8")
    settings.reload()

    assert settings.is_configured is True
    assert settings.api_key == "later-key"


def test_build_messages_adds_system_prompt_and_prompt():
    history = [{"role": "user", "content": "سلام"}, {"role": "assistant", "content": "درود"}]

    messages = build_messages(history, "خوبی؟", system_prompt="be brief")

    assert messages[0] == {"role": "system", "content": "be brief"}
    assert messages[1:] == [
        {"role": "user", "content": "سلام"},
        {"role": "assistant", "content": "درود"},
        {"role": "user", "content": "خوبی؟"},
    ]


def test_build_messages_skips_invalid_and_limits_history():
    history = [
        {"role": "user", "content": "قدیمی"},
        {"role": "system", "content": "ignored"},
        {"role": "user", "content": ""},
        {"role": "user", "content": "اول"},
        {"role": "assistant", "content": "دوم"},
        {"role": "tool", "content": "ignored"},
    ]

    messages = build_messages(history, "آخر", max_history=4)

    assert messages[0]["role"] == "system"
    assert [message["content"] for message in messages[1:]] == ["اول", "دوم", "آخر"]


class FakeStream:
    """جریان ساختگی پاسخ مدل برای تست."""

    def __init__(self, chunks, delay=0.0):
        self._chunks = list(chunks)
        self._delay = delay
        self.closed = False

    def __iter__(self):
        for chunk in self._chunks:
            if self._delay:
                time.sleep(self._delay)
            yield chunk

    def close(self):
        self.closed = True


def make_chunk(content):
    """یک قطعه پاسخ با ساختار مشابه پاسخ OpenAI می‌سازد."""
    choice = SimpleNamespace(delta=SimpleNamespace(content=content))
    return SimpleNamespace(choices=[choice])


class FakeClient:
    """کلاینت ساختگی که به‌جای شبکه، پاسخ آماده برمی‌گرداند."""

    def __init__(self, chunks=None, error=None, delay=0.0):
        self.stream = FakeStream(chunks or [], delay=delay)
        self.error = error
        self.calls = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.stream


def make_service(tmp_path, monkeypatch, api_key="test-key"):
    """سرویس گفتگو با تنظیمات موقت می‌سازد."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    env_path = write_env(tmp_path, f"OPENAI_API_KEY={api_key}\nOPENAI_MODEL=test-model\n")
    return ChatService(AppSettings(env_path))


def test_stream_reply_requires_api_key(tmp_path, monkeypatch):
    service = make_service(tmp_path, monkeypatch, api_key="")

    with pytest.raises(MissingApiKeyError):
        list(service.stream_reply([], "سلام"))


def test_stream_reply_yields_text_chunks(tmp_path, monkeypatch):
    service = make_service(tmp_path, monkeypatch)
    client = FakeClient([make_chunk("س"), make_chunk(None), make_chunk("لام")])
    monkeypatch.setattr(ChatService, "_create_client", lambda self: client)

    chunks = list(service.stream_reply([], "سلام"))

    assert "".join(chunks) == "سلام"
    assert client.stream.closed is True
    assert client.calls[0]["model"] == "test-model"
    assert client.calls[0]["stream"] is True
    assert client.calls[0]["messages"][-1] == {"role": "user", "content": "سلام"}


def test_stream_reply_stops_when_cancelled(tmp_path, monkeypatch):
    service = make_service(tmp_path, monkeypatch)
    client = FakeClient([make_chunk("یک"), make_chunk("دو"), make_chunk("سه")])
    monkeypatch.setattr(ChatService, "_create_client", lambda self: client)

    received = []
    for chunk in service.stream_reply([], "سلام", should_stop=lambda: len(received) >= 1):
        received.append(chunk)

    assert received == ["یک"]
    assert client.stream.closed is True
