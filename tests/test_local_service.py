"""تست مسیر واقعی HTTP برای سرویس‌های محلی.

سرور محلی این فایل همان قرارداد OpenAI را تقلید می‌کند تا با کلاینت واقعی (بدون
mock) بررسی شود که درخواست به `localhost` حتی وقتی پروکسی سیستمی روشن است، به
پروکسی نمی‌رود و پاسخ جریانی درست خوانده می‌شود.
"""

from __future__ import annotations

import http.server
import json
import threading
import time

import pytest

from app.services.chat_service import ChatService, ChatServiceError, is_local_base_url
from app.services.settings import AppSettings


REQUEST_COUNT = {"count": 0}


class FakeOpenAIHandler(http.server.BaseHTTPRequestHandler):
    """پاسخ‌دهنده ساختگی سازگار با OpenAI (جریانی، ۴۰۱ و ۵۰۳)."""

    mode = "stream"

    def do_POST(self) -> None:  # noqa: N802 - نام تعیین‌شده http.server
        length = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(length)
        REQUEST_COUNT["count"] += 1

        if self.mode == "busy":
            body = json.dumps(
                {"error": {"message": "overloaded", "type": "server_error"}}
            ).encode()

            self.send_response(503)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if self.mode == "unauthorized":
            body = json.dumps(
                {
                    "error": {
                        "message": "Incorrect API key provided: sk-test-secret",
                        "type": "invalid_request_error",
                        "code": "invalid_api_key",
                    }
                }
            ).encode()

            self.send_response(401)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()

        for text in ("سلام", " از ", "سرور محلی"):
            chunk = {
                "id": "chunk",
                "object": "chat.completion.chunk",
                "created": 0,
                "model": "local-model",
                "choices": [{"index": 0, "delta": {"content": text}, "finish_reason": None}],
            }
            self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
            self.wfile.flush()

        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()

    def log_message(self, *args) -> None:  # noqa: D102 - لاگ سرور لازم نیست
        pass


@pytest.fixture
def local_server():
    """یک سرور محلی روی پورت آزاد راه می‌اندازد و در پایان کامل می‌بندد."""

    def _start(mode: str = "stream"):
        handler = type("Handler", (FakeOpenAIHandler,), {"mode": mode})
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        return server, server.server_address[1]

    servers: list[http.server.HTTPServer] = []

    def factory(mode: str = "stream"):
        REQUEST_COUNT["count"] = 0
        server, port = _start(mode)
        servers.append(server)
        return port

    yield factory

    for server in servers:
        server.shutdown()
        server.server_close()


def make_settings(tmp_path, monkeypatch, port: int, *, retries: int = 0) -> AppSettings:
    """تنظیمات موقت که به سرور محلی اشاره می‌کند."""
    for variable in (
        "OPENAI_API_KEY",
        "OPENAI_MODEL",
        "OPENAI_BASE_URL",
        "OPENAI_TIMEOUT",
        "OPENAI_MAX_RETRIES",
    ):
        monkeypatch.delenv(variable, raising=False)

    env_path = tmp_path / ".env"
    env_path.write_text(
        "OPENAI_API_KEY=sk-test\n"
        "OPENAI_MODEL=local-model\n"
        f"OPENAI_BASE_URL=http://127.0.0.1:{port}/v1\n"
        "OPENAI_TIMEOUT=5\n"
        f"OPENAI_MAX_RETRIES={retries}\n",
        encoding="utf-8",
    )

    return AppSettings(env_path)


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:11434/v1",
        "http://localhost:1234/v1",
        "http://[::1]:8000/v1",
        "https://LOCALHOST/v1",
    ],
)
def test_loopback_addresses_are_recognised(url):
    assert is_local_base_url(url) is True


@pytest.mark.parametrize(
    "url",
    [
        "",
        "https://api.openai.com/v1",
        "https://my-server.test/v1",
        "http://192.168.1.10:1234/v1",
    ],
)
def test_remote_addresses_are_not_local(url):
    assert is_local_base_url(url) is False


def test_local_url_gets_a_proxy_free_client(tmp_path, monkeypatch):
    settings = make_settings(tmp_path, monkeypatch, 11434)

    options = ChatService(settings)._client_options()

    assert "http_client" in options
    assert options["http_client"].trust_env is False
    assert options["timeout"] == settings.request_timeout
    assert options["max_retries"] == 0


def test_remote_url_keeps_the_default_transport(tmp_path, monkeypatch):
    settings = AppSettings(_write_remote_env(tmp_path, monkeypatch))

    options = ChatService(settings)._client_options()

    # سرویس بیرونی باید همان رفتار پیش‌فرض (احترام به پروکسی سیستم) را داشته باشد.
    assert "http_client" not in options
    assert options["base_url"] == "https://api.openai.com/v1"


def _write_remote_env(tmp_path, monkeypatch):
    for variable in ("OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_TIMEOUT"):
        monkeypatch.delenv(variable, raising=False)

    env_path = tmp_path / "remote.env"
    env_path.write_text(
        "OPENAI_API_KEY=sk-test\nOPENAI_BASE_URL=https://api.openai.com/v1\n",
        encoding="utf-8",
    )
    return env_path


def test_streaming_from_a_local_server_reaches_the_caller(
    tmp_path, monkeypatch, local_server
):
    # این تست بدون mock و با کلاینت واقعی اجرا می‌شود: اگر پروکسی سیستمی درخواست را
    # برباید، پاسخ نمی‌رسد و تست شکست می‌خورد.
    port = local_server("stream")
    service = ChatService(make_settings(tmp_path, monkeypatch, port))

    chunks = list(service.stream_reply([], "سلام"))

    assert "".join(chunks) == "سلام از سرور محلی"


def test_real_unauthorized_error_becomes_a_friendly_message(
    tmp_path, monkeypatch, local_server
):
    port = local_server("unauthorized")
    service = ChatService(make_settings(tmp_path, monkeypatch, port))

    with pytest.raises(ChatServiceError) as caught:
        service.check_connection()

    message = str(caught.value)
    assert "کلید API پذیرفته نشد" in message
    # جزئیات خام و محرمانه SDK نباید در پیام کاربر بیاید.
    assert "sk-test-secret" not in message


def test_configured_retries_are_really_sent(tmp_path, monkeypatch, local_server):
    port = local_server("busy")
    service = ChatService(make_settings(tmp_path, monkeypatch, port, retries=2))

    with pytest.raises(ChatServiceError) as caught:
        service.check_connection()

    # یک درخواست اصلی + دو تلاش دوباره.
    assert REQUEST_COUNT["count"] == 3
    assert "موقتاً در دسترس نیست" in str(caught.value)


def test_zero_retries_means_a_single_request(tmp_path, monkeypatch, local_server):
    port = local_server("busy")
    service = ChatService(make_settings(tmp_path, monkeypatch, port, retries=0))

    with pytest.raises(ChatServiceError):
        service.check_connection()

    assert REQUEST_COUNT["count"] == 1


def test_check_connection_succeeds_against_a_local_server(
    tmp_path, monkeypatch, local_server
):
    port = local_server("stream")
    service = ChatService(make_settings(tmp_path, monkeypatch, port))

    started = time.monotonic()
    message = service.check_connection()

    assert "برقرار است" in message
    assert time.monotonic() - started < 5
