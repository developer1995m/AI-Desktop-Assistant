"""تست‌های ذخیره و بازیابی وضعیت پنجره."""

import json

from PySide6.QtGui import QGuiApplication

from app.services.storage import ConversationStore
from app.services.ui_state import (
    MIN_HEIGHT,
    MIN_WIDTH,
    UiStateStore,
)
from app.ui import main_window as main_window_module
from app.ui.main_window import MainWindow
from app.services.settings import AppSettings

from tests.test_chat_service import write_env


def make_window(tmp_path, monkeypatch, ui_state: UiStateStore) -> MainWindow:
    """پنجره اصلی با تنظیمات، پایگاه‌داده و وضعیت موقت می‌سازد."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)

    env_path = write_env(tmp_path, "OPENAI_API_KEY=key\nOPENAI_MODEL=test-model\n")
    monkeypatch.setattr(
        main_window_module, "AppSettings", lambda *args, **kwargs: AppSettings(env_path)
    )

    return MainWindow(
        chat_store=ConversationStore(tmp_path / "chat.db"),
        ui_state=ui_state,
    )


def test_missing_file_means_no_saved_state(tmp_path):
    store = UiStateStore(tmp_path / "missing.json")

    assert store.read() == {}
    assert store.window_geometry() is None
    assert store.is_maximized() is False


def test_save_and_read_round_trip(tmp_path):
    store = UiStateStore(tmp_path / "ui_state.json")

    assert store.save_window(120, 90, 950, 640, maximized=True) is True
    assert store.window_geometry() == (120, 90, 950, 640)
    assert store.is_maximized() is True


def test_corrupt_file_is_ignored(tmp_path):
    path = tmp_path / "ui_state.json"
    path.write_text("{ this is not json", encoding="utf-8")

    store = UiStateStore(path)

    assert store.read() == {}
    assert store.window_geometry() is None


def test_non_dict_payload_is_ignored(tmp_path):
    path = tmp_path / "ui_state.json"
    path.write_text("[1, 2, 3]", encoding="utf-8")

    assert UiStateStore(path).window_geometry() is None


def test_incomplete_or_invalid_geometry_is_ignored(tmp_path):
    path = tmp_path / "ui_state.json"

    payloads = [
        {"window": "nonsense"},
        {"window": {"x": 10, "y": 10, "width": 900}},
        {"window": {"x": "10", "y": 10, "width": 900, "height": 600}},
        {"window": {"x": 10, "y": 10, "width": True, "height": 600}},
        # کوچک‌تر از کمینه: پنجره‌ای که کاربر نمی‌تواند استفاده کند.
        {"window": {"x": 10, "y": 10, "width": MIN_WIDTH - 1, "height": 600}},
        {"window": {"x": 10, "y": 10, "width": 900, "height": MIN_HEIGHT - 1}},
    ]

    for payload in payloads:
        path.write_text(json.dumps(payload), encoding="utf-8")
        assert UiStateStore(path).window_geometry() is None, payload


def test_write_failure_is_reported_without_raising(tmp_path):
    # اگر مسیر یک پوشه باشد نوشتن ممکن نیست؛ ذخیره‌سازی وضعیت نباید خطا پرتاب کند.
    blocked = tmp_path / "state.json"
    blocked.mkdir()

    store = UiStateStore(blocked)

    assert store.save_window(0, 0, 900, 600) is False


def test_write_keeps_other_keys(tmp_path):
    path = tmp_path / "ui_state.json"
    path.write_text(json.dumps({"something_else": 1}), encoding="utf-8")

    store = UiStateStore(path)
    store.save_window(1, 2, 900, 600)

    content = json.loads(path.read_text(encoding="utf-8"))
    assert content["something_else"] == 1
    assert content["window"]["width"] == 900


def test_window_restores_saved_size(qt_app, tmp_path, monkeypatch):
    available = QGuiApplication.primaryScreen().availableGeometry()
    ui_state = UiStateStore(tmp_path / "ui_state.json")
    ui_state.save_window(available.x(), available.y(), 900, 620)

    window = make_window(tmp_path, monkeypatch, ui_state)
    try:
        # اندازه ذخیره‌شده روی همان نمایشگر معتبر است و باید برگردد.
        assert window.width() == 900
        assert window.height() == 620
    finally:
        window.close()


def test_window_ignores_geometry_of_a_detached_screen(qt_app, tmp_path, monkeypatch):
    ui_state = UiStateStore(tmp_path / "ui_state.json")
    # مختصاتی که روی هیچ نمایشگر فعلی نمی‌افتد؛ پنجره باید با اندازه پیش‌فرض باز شود.
    ui_state.save_window(40000, 30000, 900, 620)

    window = make_window(tmp_path, monkeypatch, ui_state)
    try:
        assert window.width() != 900 or window.height() != 620
        assert window.size().width() >= MIN_WIDTH
    finally:
        window.close()


def test_window_geometry_is_saved_on_close(qt_app, tmp_path, monkeypatch):
    ui_state = UiStateStore(tmp_path / "ui_state.json")
    window = make_window(tmp_path, monkeypatch, ui_state)

    window.setGeometry(140, 110, 940, 610)
    window.close()

    assert ui_state.window_geometry() == (140, 110, 940, 610)
    assert ui_state.is_maximized() is False
