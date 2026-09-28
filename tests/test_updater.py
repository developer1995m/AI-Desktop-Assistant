"""تست‌های آفلاین سرویس بررسی نسخه‌های جدید."""

from __future__ import annotations

import io
import hashlib
import json
import urllib.error
from pathlib import Path

import pytest

from app.services import updater


VALID_DIGEST = "a" * 64


def release_payload(**asset_changes):
    asset = {
        "name": updater.BUNDLE_ASSET_NAME,
        "browser_download_url": (
            "https://github.com/developer1995m/AI-Desktop-Assistant/"
            "releases/download/v0.2.0/AI-Desktop-Assistant-Windows-x64.zip"
        ),
        "size": 1024,
        "digest": f"sha256:{VALID_DIGEST}",
    }
    asset.update(asset_changes)
    helper = {
        "name": updater.UPDATER_ASSET_NAME,
        "browser_download_url": (
            "https://github.com/developer1995m/AI-Desktop-Assistant/"
            "releases/download/v0.2.0/AI-Desktop-Assistant-Updater.exe"
        ),
        "size": 512,
        "digest": f"sha256:{'b' * 64}",
    }
    return {
        "tag_name": "v0.2.0",
        "name": "Release 0.2.0",
        "html_url": "https://github.com/developer1995m/AI-Desktop-Assistant/releases/tag/v0.2.0",
        "assets": [asset, helper],
    }


def mock_release_response(monkeypatch, payload):
    response_body = json.dumps(payload).encode("utf-8")

    def fake_urlopen(request, timeout):
        assert request.full_url == updater.LATEST_RELEASE_URL
        assert timeout == updater._HTTP_TIMEOUT
        return io.BytesIO(response_body)

    monkeypatch.setattr(updater.urllib.request, "urlopen", fake_urlopen)


@pytest.mark.parametrize(
    ("remote_version", "expected"),
    [("v0.2.0", True), ("0.1.0", False), ("0.1.0.0", False)],
)
def test_is_newer_version(remote_version, expected):
    assert updater.is_newer_version(remote_version) is expected


def test_is_newer_version_rejects_non_numeric_tags():
    with pytest.raises(updater.UpdateError, match="نسخه نامعتبر"):
        updater.is_newer_version("v0.2.0-rc1")


def test_get_latest_release_returns_full_bundle_metadata(monkeypatch):
    mock_release_response(monkeypatch, release_payload())

    update = updater.get_latest_release()

    assert update is not None
    assert update.version == "v0.2.0"
    assert update.bundle_name == updater.BUNDLE_ASSET_NAME
    assert update.bundle_url.startswith("https://github.com/")
    assert update.bundle_size == 1024
    assert update.sha256 == VALID_DIGEST
    assert update.updater_name == updater.UPDATER_ASSET_NAME
    assert update.updater_size == 512
    assert update.updater_sha256 == "b" * 64


def test_get_latest_release_uses_safe_page_url_for_untrusted_html_url(monkeypatch):
    payload = release_payload()
    payload["html_url"] = "https://github.com/attacker/other-project/releases/tag/v0.2.0"
    mock_release_response(monkeypatch, payload)

    update = updater.get_latest_release()

    assert update is not None
    assert update.release_url == (
        f"https://github.com/{updater.GITHUB_OWNER}/"
        f"{updater.GITHUB_REPOSITORY}/releases"
    )


def test_get_latest_release_returns_none_when_release_is_not_newer(monkeypatch):
    mock_release_response(monkeypatch, {"tag_name": "v0.1.0"})

    assert updater.get_latest_release() is None


@pytest.mark.parametrize(
    ("asset_changes", "message"),
    [
        ({"name": "AI-Desktop-Assistant-Setup.exe"}, "فایل .* پیدا نشد"),
        ({"browser_download_url": "http://github.com/download.zip"}, "مخزن رسمی نیست"),
        (
            {"browser_download_url": "https://github.com/attacker/other/releases/download/x/bundle.zip"},
            "مخزن رسمی نیست",
        ),
        ({"digest": None}, "SHA-256.*موجود نیست"),
        ({"digest": "sha256:invalid"}, "SHA-256.*معتبر نیست"),
        ({"size": -1}, "اندازه فایل .* معتبر نیست"),
    ],
)
def test_get_latest_release_rejects_invalid_bundle_metadata(
    monkeypatch, asset_changes, message
):
    mock_release_response(monkeypatch, release_payload(**asset_changes))

    with pytest.raises(updater.UpdateError, match=message):
        updater.get_latest_release()


def test_get_latest_release_translates_github_http_errors(monkeypatch):
    def fail_urlopen(request, timeout):
        assert timeout == updater._HTTP_TIMEOUT
        raise urllib.error.HTTPError(
            request.full_url, 404, "Not Found", None, None
        )

    monkeypatch.setattr(updater.urllib.request, "urlopen", fail_urlopen)

    with pytest.raises(updater.UpdateError, match="Release عمومی.*مخزن خصوصی"):
        updater.get_latest_release()


def make_update(bundle_data: bytes, helper_data: bytes) -> updater.UpdateInfo:
    return updater.UpdateInfo(
        version="v0.2.0",
        release_name="Release 0.2.0",
        release_url="https://github.com/developer1995m/AI-Desktop-Assistant/releases",
        bundle_url=(
            "https://github.com/developer1995m/AI-Desktop-Assistant/"
            "releases/download/v0.2.0/bundle.zip"
        ),
        bundle_name=updater.BUNDLE_ASSET_NAME,
        bundle_size=len(bundle_data),
        sha256=hashlib.sha256(bundle_data).hexdigest(),
        updater_url=(
            "https://github.com/developer1995m/AI-Desktop-Assistant/"
            "releases/download/v0.2.0/updater.exe"
        ),
        updater_name=updater.UPDATER_ASSET_NAME,
        updater_size=len(helper_data),
        updater_sha256=hashlib.sha256(helper_data).hexdigest(),
    )


def test_download_update_verifies_both_files_and_reports_progress(
    monkeypatch, tmp_path
):
    bundle_data = b"complete application bundle"
    helper_data = b"updater executable"
    update = make_update(bundle_data, helper_data)
    assets = {
        update.bundle_url: bundle_data,
        update.updater_url: helper_data,
    }

    def fake_urlopen(request, timeout):
        assert timeout == updater._DOWNLOAD_TIMEOUT
        return io.BytesIO(assets[request.full_url])

    monkeypatch.setattr(updater.urllib.request, "urlopen", fake_urlopen)
    progress = []

    downloaded = updater.download_update(update, tmp_path, lambda done, total: progress.append((done, total)))

    assert downloaded.bundle_path.read_bytes() == bundle_data
    assert downloaded.updater_path.read_bytes() == helper_data
    assert progress[-1] == (len(bundle_data) + len(helper_data), len(bundle_data) + len(helper_data))


def test_download_update_removes_files_when_digest_is_invalid(monkeypatch, tmp_path):
    bundle_data = b"bundle"
    helper_data = b"helper"
    update = make_update(bundle_data, helper_data)
    update = updater.UpdateInfo(
        **{
            **update.__dict__,
            "updater_sha256": "0" * 64,
        }
    )
    assets = {
        update.bundle_url: bundle_data,
        update.updater_url: helper_data,
    }
    monkeypatch.setattr(
        updater.urllib.request,
        "urlopen",
        lambda request, timeout: io.BytesIO(assets[request.full_url]),
    )

    with pytest.raises(updater.UpdateError, match="SHA-256"):
        updater.download_update(update, tmp_path)

    assert not list(tmp_path.rglob("*.zip"))
    assert not list(tmp_path.rglob("*.exe"))
    assert not list(tmp_path.rglob("*.part"))


def test_launch_updater_targets_the_drive_of_the_installed_application(
    monkeypatch, tmp_path
):
    update = make_update(b"bundle", b"updater")
    bundle_path = tmp_path / "bundle.zip"
    updater_path = tmp_path / "updater.exe"
    bundle_path.write_bytes(b"bundle")
    updater_path.write_bytes(b"updater")
    downloaded = updater.DownloadedUpdate(bundle_path, updater_path)
    installed_executable = Path(r"F:\AI Desktop Assistant\AI Desktop Assistant.exe")
    launched = {}
    original_is_file = Path.is_file

    monkeypatch.setattr(updater.sys, "platform", "win32")
    monkeypatch.setattr(updater.sys, "executable", str(installed_executable))
    monkeypatch.setattr(updater, "is_frozen", lambda: True)

    def is_file(path):
        if path == installed_executable:
            return True
        return original_is_file(path)

    def fake_popen(arguments, **kwargs):
        launched["arguments"] = arguments
        launched["kwargs"] = kwargs

    monkeypatch.setattr(Path, "is_file", is_file)
    monkeypatch.setattr(updater.subprocess, "Popen", fake_popen)

    updater.launch_updater(update, downloaded)

    arguments = launched["arguments"]
    target_index = arguments.index("--target")
    assert arguments[target_index + 1] == str(installed_executable.resolve().parent)
    assert arguments[target_index + 1].startswith("F:")