"""پشتیبان‌گیری و بازیابی همه داده‌های برنامه در یک فایل JSON."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.services.paths import user_data_dir
from app.services.storage import BACKUP_TABLES, ConversationStore

BACKUP_FORMAT = "ai-desktop-assistant-backup"
BACKUP_VERSION = 1

# پشتیبان‌گیری خودکار هنگام بستن برنامه، در پوشه‌ای کنار داده‌های کاربر.
AUTO_BACKUP_FOLDER = "backups"
AUTO_BACKUP_KEEP = 5

# نام‌های فارسی جدول‌ها برای نمایش در پیام‌های کاربر.
TABLE_LABELS = {
    "conversations": "گفتگو",
    "messages": "پیام",
    "notes": "یادداشت",
    "tasks": "وظیفه",
    "memories": "حافظه",
}


class BackupError(Exception):
    """خطای پشتیبان‌گیری یا بازیابی؛ متن پیام برای نمایش مستقیم به کاربر است."""


def _now() -> str:
    """زمان جاری به شکل ISO برای ثبت در فایل پشتیبان."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def default_backup_name() -> str:
    """نام پیشنهادی فایل پشتیبان، شامل تاریخ روز."""
    return f"assistant-backup-{datetime.now().strftime('%Y%m%d')}.json"


def default_backup_folder(store: ConversationStore | None = None) -> Path:
    """پوشه‌ای که پشتیبان‌های خودکار در آن نگه داشته می‌شوند.

    پوشه کنار همان پایگاه‌داده‌ای ساخته می‌شود که پشتیبان می‌گیرد؛ اینطور در
    اجرای معمولی و نسخه بسته‌بندی‌شده هر دو درست کار می‌کند و تست‌ها هم فایل
    موقت خودشان را می‌سازند.
    """
    if store is not None and store.database_path:
        return Path(store.database_path).parent / AUTO_BACKUP_FOLDER

    return user_data_dir() / AUTO_BACKUP_FOLDER


def auto_backup(
    store: ConversationStore,
    folder: str | Path | None = None,
    *,
    keep: int = AUTO_BACKUP_KEEP,
) -> Path | None:
    """پشتیبان خودکار می‌سازد و نسخه‌های قدیمی‌تر از `keep` را پاک می‌کند.

    اگر پایگاه‌داده هیچ داده‌ای نداشته باشد فایل تازه‌ای ساخته نمی‌شود (خروجی
    `None`)، تا پوشه پشتیبان‌ها با فایل‌های خالی پر نشود.
    """
    if not any(store.snapshot().values()):
        return None

    target_folder = Path(folder) if folder is not None else default_backup_folder(store)
    path = _next_backup_path(target_folder)

    export_backup(store, path)
    prune_backups(target_folder, keep=keep)

    return path


def _next_backup_path(folder: Path) -> Path:
    """نام فایلی تازه برای پشتیبان خودکار می‌سازد.

    نام از زمان تا ثانیه به‌علاوه یک شماره دورقمی ساخته می‌شود؛ اینطور چند
    پشتیبان در یک ثانیه هم نام یکتا دارند و ترتیب الفبایی نام‌ها دقیقاً برابر
    ترتیب زمانی آن‌ها است (وگرنه چرخش نسخه‌ها می‌تواند تازه‌ترین پشتیبان را
    به‌جای قدیمی‌ترین پاک کند).
    """
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    prefix = f"auto-backup-{stamp}-"
    highest = 0

    for existing in folder.glob(f"{prefix}*.json"):
        suffix = existing.name[len(prefix) : -len(".json")]

        if suffix.isdigit():
            highest = max(highest, int(suffix))

    return folder / f"{prefix}{highest + 1:02d}.json"


def list_backups(folder: str | Path | None = None) -> list[Path]:
    """پشتیبان‌های یک پوشه را از تازه به قدیم برمی‌گرداند."""
    target_folder = Path(folder) if folder is not None else default_backup_folder()

    if not target_folder.is_dir():
        return []

    return sorted(target_folder.glob("auto-backup-*.json"), reverse=True)


def prune_backups(folder: str | Path | None = None, *, keep: int = AUTO_BACKUP_KEEP) -> list[Path]:
    """نسخه‌های اضافی پشتیبان را پاک می‌کند و فایل‌های پاک‌شده را برمی‌گرداند."""
    backups = list_backups(folder)
    removed: list[Path] = []

    for path in backups[max(0, keep) :]:
        try:
            path.unlink()
            removed.append(path)
        except OSError:
            # پاک‌نشدن یک نسخه قدیمی نباید جلوی بسته‌شدن برنامه را بگیرد.
            continue

    return removed


def export_backup(store: ConversationStore, path: str | Path) -> Path:
    """همه داده‌های برنامه را در یک فایل JSON می‌نویسد."""
    backup_path = Path(path)
    payload = {
        "format": BACKUP_FORMAT,
        "version": BACKUP_VERSION,
        "created_at": _now(),
        "tables": store.snapshot(),
    }

    try:
        if backup_path.parent != Path(""):
            backup_path.parent.mkdir(parents=True, exist_ok=True)
        backup_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError as error:
        raise BackupError(f"نوشتن فایل پشتیبان ناموفق بود: {error}") from error

    return backup_path


def read_backup(path: str | Path) -> dict[str, list[dict[str, Any]]]:
    """فایل پشتیبان را می‌خواند و اعتبار آن را بررسی می‌کند."""
    backup_path = Path(path)

    if not backup_path.is_file():
        raise BackupError(f"فایل پشتیبان پیدا نشد: {backup_path.name}")

    try:
        raw = json.loads(backup_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as error:
        raise BackupError(f"خواندن فایل پشتیبان ناموفق بود: {error}") from error
    except json.JSONDecodeError as error:
        raise BackupError("این فایل یک پشتیبان معتبر JSON نیست.") from error

    if not isinstance(raw, dict) or raw.get("format") != BACKUP_FORMAT:
        raise BackupError("این فایل پشتیبان AI Desktop Assistant نیست.")

    version = raw.get("version")
    if not isinstance(version, int):
        raise BackupError("نسخه فایل پشتیبان مشخص نیست.")
    if version > BACKUP_VERSION:
        raise BackupError(
            "این پشتیبان با نسخه جدیدتری از برنامه ساخته شده است؛ برنامه را به‌روز کنید."
        )

    tables = raw.get("tables")
    if not isinstance(tables, dict) or not tables:
        raise BackupError("فایل پشتیبان هیچ داده‌ای ندارد.")

    unknown = set(tables) - set(BACKUP_TABLES)
    if unknown:
        raise BackupError("ساختار این فایل پشتیبان با این نسخه برنامه هم‌خوان نیست.")

    return {
        table: [row for row in tables.get(table, []) if isinstance(row, dict)]
        for table in BACKUP_TABLES
    }


def summarise(tables: dict[str, list[dict[str, Any]]]) -> str:
    """خلاصه خوانا از محتوای یک پشتیبان می‌سازد."""
    parts = [
        f"{len(tables.get(table, []))} {TABLE_LABELS[table]}"
        for table in BACKUP_TABLES
        if tables.get(table)
    ]

    return "، ".join(parts) if parts else "بدون داده"


def import_backup(store: ConversationStore, path: str | Path) -> dict[str, int]:
    """داده‌های یک فایل پشتیبان را جایگزین داده‌های فعلی می‌کند."""
    tables = read_backup(path)

    try:
        counts = store.restore(tables, replace=True)
    except Exception as error:  # noqa: BLE001 - خطای SQLite باید پیام روشن بگیرد
        raise BackupError(f"بازیابی داده‌ها ناموفق بود: {error}") from error

    return counts
