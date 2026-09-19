"""تست‌های ذخیره تنظیمات و صفحه تنظیمات."""

import pytest

from app.services.chat_service import ChatService
from app.services.settings import AppSettings
from app.ui.main_window import MainWindow
from app.ui.pages.settings_page import SettingsPage

from tests.test_chat_service import FakeClient
from tests.test_error_messages import make_error
from tests.test_main_window import make_window


def make_settings(tmp_path, monkeypatch, content: str = ""):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)

    env_path = tmp_path / ".env"
    if content:
        env_path.write_text(content, encoding="utf-8")

    return AppSettings(env_path)


def test_save_writes_and_round_trips(tmp_path, monkeypatch):
    settings = make_settings(tmp_path, monkeypatch)

    settings.save(
        OPENAI_API_KEY=" key-123 ",
        OPENAI_MODEL="gpt-4o",
        OPENAI_BASE_URL="https://example.test/v1",
    )

    assert settings.api_key == "key-123"
    assert settings.model == "gpt-4o"
    assert settings.base_url == "https://example.test/v1"
    assert settings.is_configured is True

    # خواندن دوباره از دیسک هم همان مقادیر را می‌دهد.
    reloaded = AppSettings(settings.env_path)
    assert reloaded.api_key == "key-123"
    assert reloaded.model == "gpt-4o"


def test_save_empty_value_removes_variable(tmp_path, monkeypatch):
    settings = make_settings(
        tmp_path,
        monkeypatch,
        "OPENAI_API_KEY=key\nOPENAI_MODEL=model\n",
    )

    settings.save(OPENAI_API_KEY="")

    assert settings.api_key == ""
    assert settings.is_configured is False
    assert settings.model == "model"

    content = settings.env_path.read_text(encoding="utf-8")
    assert "OPENAI_API_KEY" not in content
    assert "OPENAI_MODEL=model" in content


def test_save_preserves_unknown_lines(tmp_path, monkeypatch):
    settings = make_settings(
        tmp_path,
        monkeypatch,
        "# my comment\nOPENAI_API_KEY=old\nCUSTOM_FLAG=1\n",
    )

    settings.save(OPENAI_API_KEY="new")

    content = settings.env_path.read_text(encoding="utf-8")
    lines = [line.strip() for line in content.splitlines() if line.strip()]

    assert lines[0] == "OPENAI_API_KEY=new"
    assert "# my comment" in lines
    assert "CUSTOM_FLAG=1" in lines
    assert lines.index("# my comment") > lines.index("OPENAI_API_KEY=new")


def test_save_rejects_unknown_variable(tmp_path, monkeypatch):
    settings = make_settings(tmp_path, monkeypatch)

    try:
        settings.save(SOMETHING_ELSE="x")
    except ValueError as error:
        assert "SOMETHING_ELSE" in str(error)
    else:
        raise AssertionError("ValueError expected")


def test_save_creates_env_file_and_parent_directory(tmp_path, monkeypatch):
    settings = make_settings(tmp_path / "nested" / "deeper", monkeypatch)

    settings.save(OPENAI_API_KEY="fresh-key")

    assert settings.is_configured is True
    assert (tmp_path / "nested" / "deeper" / ".env").is_file()


def test_settings_page_round_trip(qt_app, tmp_path, monkeypatch):
    settings = make_settings(tmp_path, monkeypatch)
    page = SettingsPage(settings)
    page.show()

    assert page.api_key_input.text() == ""
    assert "کلید API تنظیم نشده" in page.status_label.text()

    page.api_key_input.setText("abc")
    page.model_input.setText("gpt-4o")
    page.base_url_input.setText("https://example.test/v1")
    page.save()

    assert "تنظیمات ذخیره شد" in page.status_label.text()

    fresh_page = SettingsPage(settings)
    assert fresh_page.api_key_input.text() == "abc"
    assert fresh_page.model_input.text() == "gpt-4o"
    assert fresh_page.base_url_input.text() == "https://example.test/v1"
    assert "آماده است" in fresh_page.status_label.text()


def test_settings_page_default_model_shows_placeholder(qt_app, tmp_path, monkeypatch):
    settings = make_settings(
        tmp_path,
        monkeypatch,
        "OPENAI_API_KEY=key\nOPENAI_MODEL=gpt-4o-mini\n",
    )
    page = SettingsPage(settings)

    # مقدار پیش‌فرض به‌صورت خالی نشان داده می‌شود و از placeholder خوانده می‌شود.
    assert page.model_input.text() == ""
    assert page.model_input.placeholderText() == AppSettings.DEFAULT_MODEL

    page.model_input.setText("custom-model")
    page.save()

    assert settings.model == "custom-model"


def test_main_window_settings_page_updates_chat(qt_app, tmp_path, monkeypatch, wait_for):
    window = make_window(qt_app, tmp_path, monkeypatch)
    window.show()

    # در make_window کلید API ست شده؛ اول خالی‌اش می‌کنیم تا وضعیت «آماده» از بین برود.
    window.show_page("settings")
    window.settings_page.api_key_input.clear()
    window.settings_page.save_button.click()
    assert wait_for(lambda: "OPENAI_API_KEY" in window.chat_page.status_label.text())

    window.settings_page.api_key_input.setText("new-key")
    window.settings_page.model_input.setText("")
    window.settings_page.save_button.click()

    # ذخیره تنظیمات باید وضعیت صفحه چت را بلافاصله تازه کند؛ مدل خالی یعنی پیش‌فرض.
    assert "OPENAI_API_KEY" not in window.chat_page.status_label.text()
    assert window.chat_page.model_label.text() == f"مدل: {AppSettings.DEFAULT_MODEL}"

    window.close()


# ------------------------------------------------- زمان انتظار و تلاش دوباره


def test_timeout_and_retries_round_trip(qt_app, tmp_path, monkeypatch):
    settings = make_settings(tmp_path, monkeypatch)
    page = SettingsPage(settings)

    # مقدار پیش‌فرض با placeholder نشان داده می‌شود، نه در کادر.
    assert page.timeout_input.text() == ""
    assert page.retries_input.text() == ""

    page.timeout_input.setText("45")
    page.retries_input.setText("3")
    page.save()

    assert settings.request_timeout == 45.0
    assert settings.max_retries == 3
    assert "تنظیمات ذخیره شد" in page.status_label.text()

    fresh_page = SettingsPage(settings)
    assert fresh_page.timeout_input.text() == "45"
    assert fresh_page.retries_input.text() == "3"


def test_clearing_the_fields_restores_the_defaults(qt_app, tmp_path, monkeypatch):
    settings = make_settings(
        tmp_path,
        monkeypatch,
        "OPENAI_API_KEY=key\nOPENAI_TIMEOUT=15\nOPENAI_MAX_RETRIES=4\n",
    )
    page = SettingsPage(settings)

    assert page.timeout_input.text() == "15"
    assert page.retries_input.text() == "4"

    page.timeout_input.clear()
    page.retries_input.clear()
    page.save()

    content = settings.env_path.read_text(encoding="utf-8")
    assert "OPENAI_TIMEOUT" not in content
    assert "OPENAI_MAX_RETRIES" not in content
    assert settings.request_timeout == AppSettings.DEFAULT_TIMEOUT
    assert settings.max_retries == AppSettings.DEFAULT_RETRIES


@pytest.mark.parametrize(
    ("timeout", "retries", "expected"),
    [
        ("abc", "", "زمان انتظار باید یک عدد"),
        ("1", "", "زمان انتظار باید"),
        ("99999", "", "زمان انتظار باید"),
        ("", "x", "تعداد تلاش دوباره باید یک عدد"),
        ("", "9", "تعداد تلاش دوباره باید بین"),
        ("", "-1", "تعداد تلاش دوباره باید بین"),
    ],
)
def test_invalid_numbers_are_rejected_without_writing(
    qt_app, tmp_path, monkeypatch, timeout, retries, expected
):
    settings = make_settings(tmp_path, monkeypatch, "OPENAI_API_KEY=key\n")
    page = SettingsPage(settings)

    page.timeout_input.setText(timeout)
    page.retries_input.setText(retries)
    page.save()

    assert expected in page.status_label.text()
    assert page.status_label.property("error") == "true"

    # هیچ مقدار نامعتبری در فایل .env نوشته نمی‌شود.
    content = settings.env_path.read_text(encoding="utf-8")
    assert "OPENAI_TIMEOUT" not in content
    assert "OPENAI_MAX_RETRIES" not in content
    assert settings.request_timeout == AppSettings.DEFAULT_TIMEOUT
    assert settings.max_retries == AppSettings.DEFAULT_RETRIES


# ----------------------------------------------------------------- تست اتصال


def test_test_connection_uses_unsaved_form_values(qt_app, tmp_path, monkeypatch, wait_for):
    settings = make_settings(tmp_path, monkeypatch)
    page = SettingsPage(settings)

    client = FakeClient()
    seen = {}

    def create_client(self):
        seen["timeout"] = self._settings.request_timeout
        seen["retries"] = self._settings.max_retries
        seen["api_key"] = self._settings.api_key
        return client

    monkeypatch.setattr(ChatService, "_create_client", create_client)

    page.api_key_input.setText("form-key")
    page.timeout_input.setText("25")
    page.retries_input.setText("1")
    page.test_connection()

    assert wait_for(lambda: "برقرار است" in page.status_label.text())

    # مقادیر فرم آزمایش می‌شوند، ولی هیچ چیزی روی دیسک نوشته نمی‌شود.
    assert seen == {"timeout": 25.0, "retries": 1, "api_key": "form-key"}
    assert settings.env_path.exists() is False
    assert page.test_button.isEnabled() is True
    assert client.calls[0]["max_tokens"] == 1


def test_test_connection_reports_failure(qt_app, tmp_path, monkeypatch, wait_for):
    settings = make_settings(tmp_path, monkeypatch, "OPENAI_API_KEY=key\n")
    page = SettingsPage(settings)

    monkeypatch.setattr(
        ChatService,
        "_create_client",
        lambda self: FakeClient(error=make_error("AuthenticationError", status=401)),
    )

    page.test_connection()

    assert wait_for(lambda: "کلید API پذیرفته نشد" in page.status_label.text())
    assert page.status_label.property("error") == "true"
    assert page.test_button.isEnabled() is True


def test_test_connection_without_key_explains_what_is_missing(qt_app, tmp_path, monkeypatch, wait_for):
    settings = make_settings(tmp_path, monkeypatch)
    page = SettingsPage(settings)

    page.test_connection()

    assert wait_for(lambda: "کلید API تنظیم نشده" in page.status_label.text())
    assert page.status_label.property("error") == "true"


def test_test_connection_rejects_invalid_numbers_before_starting(qt_app, tmp_path, monkeypatch):
    settings = make_settings(tmp_path, monkeypatch, "OPENAI_API_KEY=key\n")
    page = SettingsPage(settings)

    started: list[str] = []
    monkeypatch.setattr(ChatService, "_create_client", lambda self: started.append("called"))

    page.timeout_input.setText("abc")
    page.test_connection()

    assert started == []
    assert "زمان انتظار باید یک عدد" in page.status_label.text()


def test_test_connection_does_not_overwrite_saved_values(qt_app, tmp_path, monkeypatch, wait_for):
    settings = make_settings(tmp_path, monkeypatch, "OPENAI_API_KEY=saved-key\nOPENAI_MODEL=saved-model\n")
    page = SettingsPage(settings)

    monkeypatch.setattr(ChatService, "_create_client", lambda self: FakeClient())

    page.test_connection()
    assert wait_for(lambda: "برقرار است" in page.status_label.text())

    assert settings.api_key == "saved-key"
    assert "OPENAI_MODEL=saved-model" in settings.env_path.read_text(encoding="utf-8")
