"""تست‌های موتور جایگزینی bundle در پوشه‌های موقت."""

from __future__ import annotations

import hashlib
import zipfile

import pytest

from app.services.update_installer import (
    APP_EXECUTABLE_NAME,
    UpdateInstallError,
    apply_update,
)


def make_bundle(path, *, executable=b"new exe", internal=b"new dependency"):
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(APP_EXECUTABLE_NAME, executable)
        archive.writestr("_internal/new.dll", internal)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_target(tmp_path, folder_name="AI Desktop Assistant"):
    target = tmp_path / folder_name
    (target / "_internal").mkdir(parents=True)
    (target / APP_EXECUTABLE_NAME).write_bytes(b"old exe")
    (target / "_internal/old.dll").write_bytes(b"old dependency")
    return target


def test_apply_update_replaces_the_entire_bundle(tmp_path):
    target = make_target(tmp_path)
    archive_path = tmp_path / "bundle.zip"
    expected_digest = make_bundle(archive_path)

    apply_update(archive_path, target, expected_digest)

    assert (target / APP_EXECUTABLE_NAME).read_bytes() == b"new exe"
    assert (target / "_internal/new.dll").read_bytes() == b"new dependency"
    assert not (target / "_internal/old.dll").exists()
    assert not list(tmp_path.glob(".*.backup-*"))


def test_apply_update_supports_a_custom_install_folder_name(tmp_path):
    target = make_target(tmp_path, "Assistant on F")
    archive_path = tmp_path / "bundle.zip"
    expected_digest = make_bundle(archive_path)

    apply_update(archive_path, target, expected_digest)

    assert (target / APP_EXECUTABLE_NAME).read_bytes() == b"new exe"
    assert (target / "_internal/new.dll").read_bytes() == b"new dependency"


def test_apply_update_preserves_inno_setup_uninstaller_files(tmp_path):
    target = make_target(tmp_path)
    uninstaller = target / "unins000.exe"
    uninstall_data = target / "unins000.dat"
    uninstaller.write_bytes(b"setup uninstaller")
    uninstall_data.write_bytes(b"setup uninstall data")
    archive_path = tmp_path / "bundle.zip"
    expected_digest = make_bundle(archive_path)

    apply_update(archive_path, target, expected_digest)

    assert uninstaller.read_bytes() == b"setup uninstaller"
    assert uninstall_data.read_bytes() == b"setup uninstall data"


def test_apply_update_rejects_path_traversal_without_touching_install(tmp_path):
    target = make_target(tmp_path)
    archive_path = tmp_path / "malicious.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr(APP_EXECUTABLE_NAME, b"new exe")
        archive.writestr("_internal/new.dll", b"new dependency")
        archive.writestr("../outside.txt", b"outside")

    with pytest.raises(UpdateInstallError, match="مسیر خارج"):
        apply_update(archive_path, target, hashlib.sha256(archive_path.read_bytes()).hexdigest())

    assert (target / APP_EXECUTABLE_NAME).read_bytes() == b"old exe"
    assert not (tmp_path / "outside.txt").exists()


def test_apply_update_rejects_bad_checksum_without_touching_install(tmp_path):
    target = make_target(tmp_path)
    archive_path = tmp_path / "bundle.zip"
    make_bundle(archive_path)

    with pytest.raises(UpdateInstallError, match="SHA-256"):
        apply_update(archive_path, target, "0" * 64)

    assert (target / APP_EXECUTABLE_NAME).read_bytes() == b"old exe"


def test_apply_update_rolls_back_when_restart_fails(tmp_path):
    target = make_target(tmp_path)
    archive_path = tmp_path / "bundle.zip"
    expected_digest = make_bundle(archive_path)

    def fail_to_start(executable, working_dir):
        raise OSError("simulated start failure")

    with pytest.raises(UpdateInstallError, match="اجرای نسخه جدید ناموفق بود"):
        apply_update(
            archive_path,
            target,
            expected_digest,
            restart_executable=target / APP_EXECUTABLE_NAME,
            process_starter=fail_to_start,
        )

    assert (target / APP_EXECUTABLE_NAME).read_bytes() == b"old exe"
    assert (target / "_internal/old.dll").read_bytes() == b"old dependency"
    assert not list(tmp_path.glob(".*.backup-*"))
    assert not list(tmp_path.glob(".*.failed-*"))