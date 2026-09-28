"""نقطه ورود executable مستقل updater ویندوز."""

from __future__ import annotations

import argparse
import ctypes
import os
import sys
from pathlib import Path

from app.services.update_installer import (
    APP_EXECUTABLE_NAME,
    UpdateInstallError,
    apply_update,
    sha256_file,
)


def _show_error(message: str) -> None:
    if os.name == "nt":
        ctypes.windll.user32.MessageBoxW(
            None,
            message,
            "AI Desktop Assistant Update",
            0x10 | 0x1000,
        )
    else:
        print(message, file=sys.stderr)


def _parse_arguments(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--target", required=True, type=Path)
    parser.add_argument("--bundle-sha256", required=True)
    parser.add_argument("--updater-sha256", required=True)
    parser.add_argument("--wait-pid", required=True, type=int)
    parser.add_argument("--restart", required=True, type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    try:
        if os.name != "nt" or not getattr(sys, "frozen", False):
            raise UpdateInstallError("این فایل فقط به‌صورت executable ویندوز اجرا می‌شود.")

        arguments = _parse_arguments(argv)
        updater_executable = Path(sys.executable).resolve()
        if sha256_file(updater_executable).lower() != arguments.updater_sha256.lower():
            raise UpdateInstallError("SHA-256 فایل updater معتبر نیست.")

        target = arguments.target.resolve()
        restart = arguments.restart.resolve()
        if restart.parent != target or restart.name != APP_EXECUTABLE_NAME:
            raise UpdateInstallError("مسیر اجرای دوباره برنامه معتبر نیست.")

        apply_update(
            arguments.archive,
            target,
            arguments.bundle_sha256,
            wait_pid=arguments.wait_pid,
            restart_executable=restart,
        )
    except (UpdateInstallError, OSError, ValueError) as error:
        _show_error(str(error))
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())