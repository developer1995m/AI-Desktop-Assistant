"""تست‌های پیام خطای قابل‌فهم برای خطاهای شبکه و سرویس مدل."""

import pytest

from app.services.chat_service import ChatService, ChatServiceError, describe_error
from app.ui.workers import ChatStreamWorker, ConnectionTestWorker

from tests.test_chat_service import FakeClient, make_service


def make_error(name: str, *, status: int | None = None, message: str = "boom"):
    """یک کلاس خطا با نام و کد وضعیت دلخواه می‌سازد (شبیه خطاهای کتابخانه)."""
    return type(name, (Exception,), {"status_code": status})(message)


def test_service_errors_pass_through():
    assert describe_error(ChatServiceError("متن فارسی")) == "متن فارسی"


@pytest.mark.parametrize(
    ("name", "status", "expected"),
    [
        ("AuthenticationError", 401, "کلید API پذیرفته نشد"),
        ("PermissionDeniedError", 403, "کلید API پذیرفته نشد"),
        ("NotFoundError", 404, "پیدا نشد"),
        ("RateLimitError", 429, "سهمیه"),
        ("InternalServerError", 503, "موقتاً در دسترس نیست"),
        ("APITimeoutError", None, "زمان مقرر نرسید"),
        ("APIConnectionError", None, "اتصال به اینترنت"),
        ("BadRequestError", 400, "درخواست پذیرفته نشد"),
    ],
)
def test_known_errors_are_explained_in_persian(name, status, expected):
    assert expected in describe_error(make_error(name, status=status))


def test_raw_english_detail_is_not_shown_for_known_categories():
    error = make_error("AuthenticationError", status=401, message="Invalid API key provided: sk-x")

    message = describe_error(error)

    assert "sk-x" not in message
    assert "Invalid API key" not in message


def test_unexpected_error_keeps_the_class_name_for_diagnosis():
    message = describe_error(make_error("WeirdError", message="something odd"))

    assert "WeirdError" in message
    assert "something odd" in message


def test_plain_oserror_is_treated_as_a_connection_problem():
    assert "اتصال" in describe_error(OSError("network unreachable"))


def collect(signal):
    """مقادیر منتشرشده یک سیگنال را جمع می‌کند."""
    received: list[str] = []
    signal.connect(received.append)
    return received


def test_stream_worker_reports_a_friendly_message(tmp_path, monkeypatch):
    service = make_service(tmp_path, monkeypatch)
    monkeypatch.setattr(
        ChatService,
        "_create_client",
        lambda self: FakeClient(error=make_error("APIConnectionError")),
    )

    worker = ChatStreamWorker(service, [], "سلام")
    failures = collect(worker.failed)

    worker.run()

    assert len(failures) == 1
    assert "اتصال به اینترنت" in failures[0]


def test_stream_worker_reports_missing_key(tmp_path, monkeypatch):
    service = make_service(tmp_path, monkeypatch, api_key="")

    worker = ChatStreamWorker(service, [], "سلام")
    failures = collect(worker.failed)

    worker.run()

    assert "کلید API تنظیم نشده" in failures[0]


def test_stopped_request_reports_no_error(tmp_path, monkeypatch):
    # وقتی کاربر خودش Stop زده، خطای بعدی (مثلاً پایان مهلت خواندن) مشکل واقعی نیست.
    service = make_service(tmp_path, monkeypatch)
    monkeypatch.setattr(
        ChatService, "_create_client", lambda self: FakeClient(error=make_error("APITimeoutError"))
    )

    worker = ChatStreamWorker(service, [], "سلام")
    failures = collect(worker.failed)
    worker.request_stop()

    worker.run()

    assert failures == []


def test_connection_worker_reports_success(tmp_path, monkeypatch):
    service = make_service(tmp_path, monkeypatch)
    monkeypatch.setattr(ChatService, "_create_client", lambda self: FakeClient())

    worker = ConnectionTestWorker(service)
    succeeded = collect(worker.succeeded)
    failures = collect(worker.failed)

    worker.run()

    assert failures == []
    assert "test-model" in succeeded[0]


def test_connection_worker_reports_failure(tmp_path, monkeypatch):
    service = make_service(tmp_path, monkeypatch)
    monkeypatch.setattr(
        ChatService,
        "_create_client",
        lambda self: FakeClient(error=make_error("AuthenticationError", status=401)),
    )

    worker = ConnectionTestWorker(service)
    succeeded = collect(worker.succeeded)
    failures = collect(worker.failed)

    worker.run()

    assert succeeded == []
    assert "کلید API پذیرفته نشد" in failures[0]


def test_check_connection_sends_a_minimal_request(tmp_path, monkeypatch):
    service = make_service(tmp_path, monkeypatch)
    client = FakeClient()
    monkeypatch.setattr(ChatService, "_create_client", lambda self: client)

    service.check_connection()

    assert client.calls[0]["max_tokens"] == 1
    assert client.calls[0]["model"] == "test-model"
