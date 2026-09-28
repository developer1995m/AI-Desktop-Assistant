"""سرویس بررسی نسخه‌های جدید برنامه."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from app.services.paths import is_frozen
from app.version import APP_NAME, APP_VERSION


GITHUB_OWNER = "developer1995m"
GITHUB_REPOSITORY = "AI-Desktop-Assistant"

LATEST_RELEASE_URL = (
    f"https://api.github.com/repos/"
    f"{GITHUB_OWNER}/{GITHUB_REPOSITORY}/releases/latest"
)

BUNDLE_ASSET_NAME = "AI-Desktop-Assistant-Windows-x64.zip"
UPDATER_ASSET_NAME = "AI-Desktop-Assistant-Updater.exe"

_HTTP_TIMEOUT = 15
_DOWNLOAD_TIMEOUT = 30
_DOWNLOAD_CHUNK_SIZE = 1024 * 1024


@dataclass(frozen=True)
class UpdateInfo:
    """اطلاعات یک نسخه جدید."""

    version: str
    release_name: str
    release_url: str
    bundle_url: str
    bundle_name: str
    bundle_size: int
    sha256: str
    updater_url: str
    updater_name: str
    updater_size: int
    updater_sha256: str


@dataclass(frozen=True)
class DownloadedUpdate:
    """فایل‌های دانلودشده و اعتبارسنجی‌شده برای نصب."""

    bundle_path: Path
    updater_path: Path


class UpdateError(RuntimeError):
    """خطای مربوط به بررسی یا دریافت آپدیت."""


def _normalize_version(version: str) -> tuple[int, ...]:
    """نسخه را به tuple عددی قابل مقایسه تبدیل می‌کند."""

    value = version.strip()

    if value.lower().startswith("v"):
        value = value[1:]

    match = re.fullmatch(r"(\d+)(?:\.(\d+))?(?:\.(\d+))?(?:\.(\d+))?", value)

    if not match:
        raise UpdateError(f"نسخه نامعتبر است: {version}")

    numbers = tuple(int(part or 0) for part in match.groups())

    return numbers


def is_newer_version(remote_version: str, current_version: str = APP_VERSION) -> bool:
    """بررسی می‌کند آیا نسخه راه دور از نسخه فعلی جدیدتر است."""

    return _normalize_version(remote_version) > _normalize_version(current_version)


def _is_trusted_github_url(url: str, *, download_asset: bool = False) -> bool:
    parsed_url = urlparse(url)
    expected_path = f"/{GITHUB_OWNER}/{GITHUB_REPOSITORY}/releases/"

    if download_asset:
        expected_path += "download/"

    return (
        parsed_url.scheme == "https"
        and parsed_url.hostname == "github.com"
        and parsed_url.username is None
        and parsed_url.password is None
        and parsed_url.path.startswith(expected_path)
    )


def _release_asset(payload: dict, name: str) -> tuple[str, int, str]:
    assets = payload.get("assets")

    if not isinstance(assets, list):
        raise UpdateError("فهرست فایل‌های Release معتبر نیست.")

    asset = next(
        (
            item
            for item in assets
            if isinstance(item, dict) and item.get("name") == name
        ),
        None,
    )
    if asset is None:
        raise UpdateError(f"فایل {name} در Release پیدا نشد.")

    url = asset.get("browser_download_url")
    if not isinstance(url, str) or not _is_trusted_github_url(url, download_asset=True):
        raise UpdateError(f"آدرس فایل {name} از مخزن رسمی نیست.")

    size = asset.get("size")
    if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
        raise UpdateError(f"اندازه فایل {name} در Release معتبر نیست.")

    digest = asset.get("digest")
    if not isinstance(digest, str) or not digest.startswith("sha256:"):
        raise UpdateError(f"SHA-256 فایل {name} در Release موجود نیست.")
    digest = digest.removeprefix("sha256:")
    if re.fullmatch(r"[0-9a-fA-F]{64}", digest) is None:
        raise UpdateError(f"SHA-256 فایل {name} در Release معتبر نیست.")

    return url, size, digest


def _request_json(url: str) -> dict:
    """یک درخواست JSON به GitHub API ارسال می‌کند."""

    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"{GITHUB_REPOSITORY}/{APP_VERSION}",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=_HTTP_TIMEOUT) as response:
            payload = response.read()
    except urllib.error.HTTPError as error:
        raise UpdateError(
            f"GitHub API خطای HTTP {error.code} برگرداند."
        ) from error
    except urllib.error.URLError as error:
        raise UpdateError(
            f"اتصال به GitHub ممکن نبود: {error.reason}"
        ) from error
    except TimeoutError as error:
        raise UpdateError("زمان اتصال به GitHub تمام شد.") from error

    try:
        result = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise UpdateError("پاسخ GitHub معتبر نیست.") from error

    if not isinstance(result, dict):
        raise UpdateError("ساختار پاسخ GitHub معتبر نیست.")

    return result


def get_latest_release() -> UpdateInfo | None:
    """آخرین Release پایدار را بررسی می‌کند.

    اگر نسخه جدیدی وجود نداشته باشد، None برمی‌گرداند.
    """

    payload = _request_json(LATEST_RELEASE_URL)

    tag_name = payload.get("tag_name")

    if not isinstance(tag_name, str) or not tag_name.strip():
        raise UpdateError("نسخه Release در پاسخ GitHub پیدا نشد.")

    if not is_newer_version(tag_name):
        return None

    bundle_url, bundle_size, bundle_digest = _release_asset(
        payload, BUNDLE_ASSET_NAME
    )
    updater_url, updater_size, updater_digest = _release_asset(
        payload, UPDATER_ASSET_NAME
    )

    release_url = payload.get("html_url")

    if not isinstance(release_url, str) or not _is_trusted_github_url(release_url):
        release_url = f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPOSITORY}/releases"

    release_name = payload.get("name")

    if not isinstance(release_name, str) or not release_name:
        release_name = tag_name

    return UpdateInfo(
        version=tag_name,
        release_name=release_name,
        release_url=release_url,
        bundle_url=bundle_url,
        bundle_name=BUNDLE_ASSET_NAME,
        bundle_size=bundle_size,
        sha256=bundle_digest,
        updater_url=updater_url,
        updater_name=UPDATER_ASSET_NAME,
        updater_size=updater_size,
        updater_sha256=updater_digest,
    )


def download_update(
    update: UpdateInfo,
    destination_dir: Path,
    progress_callback: Callable[[int, int], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> DownloadedUpdate:
    """هر دو فایل نسخه را دانلود می‌کند و اندازه و SHA-256 را بررسی می‌کند."""

    destination_dir = Path(destination_dir)
    version_folder = destination_dir / update.version
    version_folder.mkdir(parents=True, exist_ok=True)
    bundle_path = version_folder / update.bundle_name
    updater_path = version_folder / update.updater_name
    total_size = update.bundle_size + update.updater_size
    downloaded_before = 0

    def report_bundle_progress(current_bytes: int) -> None:
        if progress_callback is not None:
            progress_callback(current_bytes, total_size)

    try:
        _download_asset(
            update.bundle_url,
            bundle_path,
            update.bundle_size,
            update.sha256,
            report_bundle_progress,
            cancel_check,
        )
        downloaded_before = update.bundle_size

        def report_updater_progress(current_bytes: int) -> None:
            if progress_callback is not None:
                progress_callback(downloaded_before + current_bytes, total_size)

        _download_asset(
            update.updater_url,
            updater_path,
            update.updater_size,
            update.updater_sha256,
            report_updater_progress,
            cancel_check,
        )
    except UpdateError:
        bundle_path.unlink(missing_ok=True)
        updater_path.unlink(missing_ok=True)
        raise

    return DownloadedUpdate(bundle_path=bundle_path, updater_path=updater_path)


def _download_asset(
    url: str,
    destination: Path,
    expected_size: int,
    expected_digest: str,
    progress_callback: Callable[[int], None],
    cancel_check: Callable[[], bool] | None,
) -> None:
    if not _is_trusted_github_url(url, download_asset=True):
        raise UpdateError("آدرس دانلود از مخزن رسمی نیست.")

    partial_path = destination.with_name(f"{destination.name}.part")
    partial_path.unlink(missing_ok=True)
    digest = hashlib.sha256()
    received = 0

    try:
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/octet-stream",
                "User-Agent": f"{GITHUB_REPOSITORY}/{APP_VERSION}",
            },
        )
        with urllib.request.urlopen(request, timeout=_DOWNLOAD_TIMEOUT) as response:
            with partial_path.open("wb") as output:
                while True:
                    if cancel_check is not None and cancel_check():
                        raise UpdateError("دانلود به‌دلیل بسته‌شدن برنامه لغو شد.")
                    chunk = response.read(_DOWNLOAD_CHUNK_SIZE)
                    if not chunk:
                        break

                    received += len(chunk)
                    if received > expected_size:
                        raise UpdateError("اندازه فایل دانلودشده از Release بیشتر است.")

                    output.write(chunk)
                    digest.update(chunk)
                    progress_callback(received)
    except urllib.error.HTTPError as error:
        partial_path.unlink(missing_ok=True)
        raise UpdateError(f"دانلود فایل با خطای HTTP {error.code} متوقف شد.") from error
    except urllib.error.URLError as error:
        partial_path.unlink(missing_ok=True)
        raise UpdateError(f"دانلود فایل ممکن نبود: {error.reason}") from error
    except TimeoutError as error:
        partial_path.unlink(missing_ok=True)
        raise UpdateError("زمان دانلود فایل تمام شد.") from error
    except OSError as error:
        partial_path.unlink(missing_ok=True)
        raise UpdateError(f"ذخیره فایل دانلودشده ممکن نبود: {error}") from error
    except UpdateError:
        partial_path.unlink(missing_ok=True)
        raise

    if received != expected_size:
        partial_path.unlink(missing_ok=True)
        raise UpdateError("اندازه فایل دانلودشده با Release مطابقت ندارد.")

    if digest.hexdigest().lower() != expected_digest.lower():
        partial_path.unlink(missing_ok=True)
        raise UpdateError("اعتبارسنجی SHA-256 فایل دانلودشده ناموفق بود.")

    try:
        os.replace(partial_path, destination)
    except OSError as error:
        partial_path.unlink(missing_ok=True)
        raise UpdateError(f"ذخیره فایل دانلودشده ممکن نبود: {error}") from error


def launch_updater(update: UpdateInfo, downloaded: DownloadedUpdate) -> None:
    """Updater جداگانه را پس از اعتبارسنجی از پوشه داده کاربر اجرا می‌کند."""

    if sys.platform != "win32" or not is_frozen():
        raise UpdateError("نصب خودکار فقط در نسخه بسته‌بندی‌شده ویندوز در دسترس است.")

    target_dir = Path(sys.executable).resolve().parent
    app_executable = target_dir / f"{APP_NAME}.exe"
    if not app_executable.is_file():
        raise UpdateError("مسیر نصب برنامه معتبر نیست.")
    if not downloaded.updater_path.is_file() or not downloaded.bundle_path.is_file():
        raise UpdateError("فایل‌های دانلودشده برای نصب کامل نیستند.")

    arguments = [
        str(downloaded.updater_path),
        "--archive",
        str(downloaded.bundle_path),
        "--target",
        str(target_dir),
        "--bundle-sha256",
        update.sha256,
        "--updater-sha256",
        update.updater_sha256,
        "--wait-pid",
        str(os.getpid()),
        "--restart",
        str(app_executable),
    ]
    creation_flags = (
        getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
        | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
        | getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    )

    try:
        subprocess.Popen(
            arguments,
            cwd=downloaded.updater_path.parent,
            close_fds=True,
            creationflags=creation_flags,
        )
    except OSError as error:
        raise UpdateError(f"اجرای updater ممکن نبود: {error}") from error