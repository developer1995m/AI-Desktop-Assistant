"""تعویض امن پوشه‌ی برنامه توسط فرایند updater مستقل."""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
import subprocess
import tempfile
import zipfile
from collections.abc import Callable
from pathlib import Path

APP_EXECUTABLE_NAME = "AI Desktop Assistant.exe"
MAX_ARCHIVE_SIZE = 2 * 1024 * 1024 * 1024
MAX_ARCHIVE_FILES = 100_000
_COPY_BUFFER_SIZE = 1024 * 1024


class UpdateInstallError(RuntimeError):
    """خطای اعتبارسنجی یا جایگزینی bundle برنامه."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        while chunk := source.read(_COPY_BUFFER_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def wait_for_process(process_id: int, timeout_ms: int = 120_000) -> None:
    """در ویندوز تا بسته‌شدن برنامه‌ی اصلی صبر می‌کند."""
    if os.name != "nt":
        raise UpdateInstallError("Updater فقط روی ویندوز قابل اجراست.")

    import ctypes
    from ctypes import wintypes

    synchronize = 0x00100000
    wait_object_0 = 0
    wait_timeout = 0x00000102
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL
    handle = kernel32.OpenProcess(synchronize, False, process_id)

    if not handle:
        if ctypes.get_last_error() == 87:
            return
        raise UpdateInstallError("فرایند برنامه برای انتظار پیدا نشد.")

    try:
        result = kernel32.WaitForSingleObject(handle, timeout_ms)
        if result == wait_timeout:
            raise UpdateInstallError("بسته‌شدن برنامه بیش از حد طول کشید.")
        if result != wait_object_0:
            raise UpdateInstallError("انتظار برای بسته‌شدن برنامه ناموفق بود.")
    finally:
        kernel32.CloseHandle(handle)


def _safe_member_parts(info: zipfile.ZipInfo) -> tuple[str, ...]:
    raw_name = info.filename
    if "\\" in raw_name or "\x00" in raw_name:
        raise UpdateInstallError("ZIP شامل مسیر نامعتبر است.")

    trimmed_name = raw_name[:-1] if info.is_dir() and raw_name.endswith("/") else raw_name
    parts = trimmed_name.split("/")
    if (
        not trimmed_name
        or any(part in ("", ".", "..") for part in parts)
        or ":" in trimmed_name
        or any(part.endswith((".", " ")) for part in parts)
    ):
        raise UpdateInstallError("ZIP شامل مسیر خارج از پوشه برنامه است.")

    mode = info.external_attr >> 16
    if stat.S_ISLNK(mode):
        raise UpdateInstallError("ZIP شامل پیوند نمادین غیرمجاز است.")

    return tuple(parts)


def _extract_bundle(archive_path: Path, stage_dir: Path) -> None:
    try:
        with zipfile.ZipFile(archive_path) as archive:
            entries = archive.infolist()
            if len(entries) > MAX_ARCHIVE_FILES:
                raise UpdateInstallError("تعداد فایل‌های ZIP بیش از حد مجاز است.")

            expected_total = sum(info.file_size for info in entries)
            if expected_total > MAX_ARCHIVE_SIZE:
                raise UpdateInstallError("حجم بازشده‌ی ZIP بیش از حد مجاز است.")

            seen_paths: set[str] = set()
            actual_total = 0
            for info in entries:
                parts = _safe_member_parts(info)
                relative_name = "/".join(parts).casefold()
                if relative_name in seen_paths:
                    raise UpdateInstallError("ZIP شامل نام فایل تکراری است.")
                seen_paths.add(relative_name)

                destination = stage_dir.joinpath(*parts)
                if info.is_dir():
                    destination.mkdir(parents=True, exist_ok=True)
                    continue

                destination.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as source, destination.open("wb") as output:
                    while chunk := source.read(_COPY_BUFFER_SIZE):
                        actual_total += len(chunk)
                        if actual_total > MAX_ARCHIVE_SIZE:
                            raise UpdateInstallError("حجم بازشده‌ی ZIP بیش از حد مجاز است.")
                        output.write(chunk)
    except zipfile.BadZipFile as error:
        raise UpdateInstallError("فایل bundle یک ZIP معتبر نیست.") from error
    except OSError as error:
        raise UpdateInstallError(f"استخراج bundle ممکن نبود: {error}") from error

    executable = stage_dir / APP_EXECUTABLE_NAME
    internal_dir = stage_dir / "_internal"
    if not executable.is_file() or not internal_dir.is_dir():
        raise UpdateInstallError("bundle شامل executable یا پوشه _internal نیست.")


def _start_application(executable: Path, target_dir: Path) -> None:
    subprocess.Popen([str(executable)], cwd=target_dir, close_fds=True)


def apply_update(
    archive_path: Path,
    target_dir: Path,
    expected_sha256: str,
    *,
    wait_pid: int | None = None,
    restart_executable: Path | None = None,
    process_starter: Callable[[Path, Path], None] = _start_application,
) -> None:
    """bundle را در کنار مقصد آماده و با rollback جایگزین می‌کند."""
    archive_path = Path(archive_path).resolve()
    requested_target = Path(target_dir)
    if requested_target.is_symlink() or requested_target.is_junction():
        raise UpdateInstallError("مسیر نصب نمی‌تواند پیوند نمادین باشد.")
    target = requested_target.resolve()
    if not target.is_dir() or target.name != "AI Desktop Assistant":
        raise UpdateInstallError("پوشه نصب برنامه معتبر نیست.")
    if not archive_path.is_file():
        raise UpdateInstallError("فایل bundle پیدا نشد.")
    if sha256_file(archive_path).lower() != expected_sha256.lower():
        raise UpdateInstallError("SHA-256 فایل bundle معتبر نیست.")

    if wait_pid is not None:
        wait_for_process(wait_pid)

    parent = target.parent
    stage_dir = Path(tempfile.mkdtemp(prefix=f".{target.name}.stage-", dir=parent))
    backup_dir = parent / f".{target.name}.backup-{os.getpid()}"
    failed_dir = parent / f".{target.name}.failed-{os.getpid()}"

    try:
        _extract_bundle(archive_path, stage_dir)
        if backup_dir.exists() or failed_dir.exists():
            raise UpdateInstallError("پوشه موقت updater از اجرای قبلی باقی مانده است.")

        os.replace(target, backup_dir)
        try:
            os.replace(stage_dir, target)
        except OSError as error:
            os.replace(backup_dir, target)
            raise UpdateInstallError(f"جایگزینی bundle ناموفق بود: {error}") from error

        if restart_executable is not None:
            executable = target / Path(restart_executable).name
            try:
                process_starter(executable, target)
            except OSError as error:
                os.replace(target, failed_dir)
                os.replace(backup_dir, target)
                shutil.rmtree(failed_dir, ignore_errors=True)
                raise UpdateInstallError(f"اجرای نسخه جدید ناموفق بود: {error}") from error

        shutil.rmtree(backup_dir, ignore_errors=True)
    finally:
        if stage_dir.exists():
            shutil.rmtree(stage_dir, ignore_errors=True)