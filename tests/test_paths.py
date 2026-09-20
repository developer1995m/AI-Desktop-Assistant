"""تست‌های مسیرهای داده برنامه و حالت خودآزمایی."""

import os
import sys

import pytest

import main as main_module
from app.services import paths, settings, storage
from app.services.paths import APPLICATION_FOLDER, PROJECT_ROOT, database_path, env_path, user_data_dir


@pytest.fixture
def isolated_application_defaults(tmp_path, monkeypatch):
    """پیش‌فرض‌های production را برای self-check به مسیر موقت می‌برد."""
    monkeypatch.setattr(paths, "is_frozen", lambda: True)
    monkeypatch.setenv("APPDATA", str(tmp_path / "AppData"))
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.setattr(storage, "DEFAULT_DATABASE_PATH", tmp_path / "assistant.db")
    monkeypatch.setattr(settings, "DEFAULT_ENV_PATH", tmp_path / ".env")


def test_source_run_uses_project_root(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)

    assert paths.is_frozen() is False
    assert user_data_dir() == PROJECT_ROOT
    assert database_path() == PROJECT_ROOT / "data" / "assistant.db"
    assert env_path() == PROJECT_ROOT / ".env"


def test_frozen_run_uses_appdata(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)

    assert paths.is_frozen() is True
    assert user_data_dir() == tmp_path / "Roaming" / APPLICATION_FOLDER
    assert database_path() == tmp_path / "Roaming" / APPLICATION_FOLDER / "data" / "assistant.db"


def test_frozen_run_without_appdata_falls_back_to_home(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.delenv("APPDATA", raising=False)
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.setattr(paths.Path, "home", staticmethod(lambda: tmp_path))

    assert user_data_dir() == tmp_path / ".local" / "share" / APPLICATION_FOLDER


def test_frozen_run_honours_xdg_data_home(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.delenv("APPDATA", raising=False)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "share"))

    assert user_data_dir() == tmp_path / "share" / APPLICATION_FOLDER


def test_resource_dir_in_source_run(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)

    assert paths.resource_dir() == PROJECT_ROOT / "assets"


def test_resource_dir_in_frozen_run(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "bundle"), raising=False)

    assert paths.resource_dir() == tmp_path / "bundle" / "assets"


def test_resource_dir_falls_back_to_project_assets(monkeypatch):
    # اگر PyInstaller پوشه موقت را کنار نگذاشته باشد، بازگشت به assets پروژه داریم.
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)

    assert paths.resource_dir() == PROJECT_ROOT / "assets"


def test_ui_state_path_follows_user_data_dir(monkeypatch, tmp_path):
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert paths.ui_state_path() == PROJECT_ROOT / "data" / "ui_state.json"

    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert paths.ui_state_path() == tmp_path / APPLICATION_FOLDER / "data" / "ui_state.json"


def test_storage_and_settings_defaults_follow_paths(monkeypatch, tmp_path):
    """پیش‌فرض پایگاه‌داده و فایل تنظیمات باید از همین لایه مسیر بیایند."""
    from app.services import settings, storage

    monkeypatch.setattr(paths, "is_frozen", lambda: True)
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)

    assert paths.database_path() == tmp_path / APPLICATION_FOLDER / "data" / "assistant.db"
    assert paths.env_path() == tmp_path / APPLICATION_FOLDER / ".env"
    # مقادیر پیش‌فرض ماژول‌ها در زمان import ساخته شده‌اند و به ریشه پروژه اشاره می‌کنند.
    assert storage.DEFAULT_DATABASE_PATH == PROJECT_ROOT / "data" / "assistant.db"
    assert settings.DEFAULT_ENV_PATH == PROJECT_ROOT / ".env"


def test_self_check_passes_on_this_environment(qt_app, isolated_application_defaults):
    """حالت خودآزمایی باید در محیط سالم با کد خروج صفر تمام شود."""
    assert main_module.run_self_check(qt_app) == 0


def test_main_returns_zero_for_self_check(qt_app, isolated_application_defaults):
    assert main_module.main([main_module.SELF_CHECK_FLAG]) == 0


def test_self_check_does_not_use_production_defaults(qt_app, tmp_path, monkeypatch):
    production_database = tmp_path / "production.db"
    production_env = tmp_path / "production.env"
    monkeypatch.setattr(storage, "DEFAULT_DATABASE_PATH", production_database)
    monkeypatch.setattr(settings, "DEFAULT_ENV_PATH", production_env)
    monkeypatch.setenv("OPENAI_API_KEY", "must-be-restored")

    assert main_module.run_self_check(qt_app) == 0
    assert not production_database.exists()
    assert not production_env.exists()
    assert not (tmp_path / "data").exists()
    assert not (tmp_path / "backups").exists()
    assert os.environ["OPENAI_API_KEY"] == "must-be-restored"


def test_report_survives_missing_console(monkeypatch):
    """در بسته‌بندی پنجره‌ای، جریان خروجی وجود ندارد و چاپ نباید خطا بدهد."""
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)

    main_module._report("self-check: OK")
    main_module._report("self-check: FAILED", error=True)
