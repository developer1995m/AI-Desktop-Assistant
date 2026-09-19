"""ذخیره‌سازی محلی گفتگوها و پیام‌ها در SQLite."""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

from app.services.paths import database_path as default_database_path

DEFAULT_DATABASE_PATH = default_database_path()

MESSAGE_ROLES = ("user", "assistant")
TASK_PRIORITIES = ("low", "normal", "high")
TASK_PRIORITY_LABELS = {"low": "کم", "normal": "معمولی", "high": "مهم"}
MAX_MEMORY_CHARS = 400
MAX_NOTE_TAGS = 8
MAX_TAG_CHARS = 24

# جدول‌هایی که در پشتیبان‌گیری و بازیابی شرکت می‌کنند (ترتیب درج: والد قبل از فرزند).
BACKUP_TABLES = ("conversations", "messages", "notes", "tasks", "memories")

SEARCH_KINDS = ("conversation", "note", "task", "memory")
SEARCH_LIMIT_PER_KIND = 5
SEARCH_SNIPPET_RADIUS = 60

SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (conversation_id) REFERENCES conversations (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages (conversation_id, id);

CREATE TABLE IF NOT EXISTS notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    tags TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    done INTEGER NOT NULL DEFAULT 0,
    priority TEXT NOT NULL DEFAULT 'normal',
    due_date TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_tasks_done ON tasks (done, id);

CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""

# ستون‌هایی که پس از نسخه نخست به جدول‌ها اضافه شده‌اند. پایگاه‌داده‌های موجود با
# ALTER TABLE به‌روز می‌شوند تا کاربر برای گرفتن قابلیت تازه، داده‌اش را از دست ندهد.
MIGRATIONS: dict[str, dict[str, str]] = {
    "notes": {"tags": "TEXT NOT NULL DEFAULT ''"},
    "tasks": {"due_date": "TEXT NOT NULL DEFAULT ''"},
}


def _timestamp() -> str:
    """زمان جاری را به شکل قابل مرتب‌سازی برمی‌گرداند."""
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def normalise_title(text: str, max_length: int = 60) -> str:
    """اولین پیام کاربر را به یک عنوان تک‌خطی و کوتاه تبدیل می‌کند."""
    title = " ".join(text.split())

    if not title:
        return "گفتگوی بدون عنوان"

    if len(title) > max_length:
        return title[: max_length - 1].rstrip() + "…"

    return title


def parse_tags(text: str) -> tuple[str, ...]:
    """متن برچسب‌ها را به فهرست برچسب‌های تمیز و بی‌همتا تبدیل می‌کند.

    جداکننده کاما (فارسی یا انگلیسی) است، فاصله‌های تکراری جمع می‌شوند و تکرار
    برچسب‌ها (بدون توجه به بزرگی و کوچکی حروف) نگه داشته نمی‌شود.
    """
    tags: list[str] = []
    seen: set[str] = set()

    for chunk in text.replace("،", ",").split(","):
        tag = " ".join(chunk.split())[:MAX_TAG_CHARS].strip()
        key = tag.casefold()

        if not tag or key in seen:
            continue

        seen.add(key)
        tags.append(tag)

        if len(tags) >= MAX_NOTE_TAGS:
            break

    return tuple(tags)


def normalise_tags(text: str) -> str:
    """برچسب‌ها را به شکل ذخیره‌سازی (جدا شده با کاما) تبدیل می‌کند."""
    return ", ".join(parse_tags(text))


def normalise_due_date(value: str) -> str:
    """موعد را به شکل استاندارد `YYYY-MM-DD` برمی‌گرداند (خالی یعنی بدون موعد)."""
    text = (value or "").strip()

    if not text:
        return ""

    try:
        return date.fromisoformat(text).isoformat()
    except ValueError:
        raise ValueError(f"تاریخ نامعتبر: {value}") from None


def _like_pattern(query: str) -> str:
    r"""عبارت جست‌وجو را به الگوی امن LIKE تبدیل می‌کند.

    نویسه‌های ویژه LIKE (درصد، زیرخط و بک‌اسلش) بی‌اثر می‌شوند تا جست‌وجوی
    متن آزاد کاربر رفتار غیرمنتظره نداشته باشد.
    """
    escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

    return f"%{escaped}%"


def snippet_from(text: str, query: str, radius: int = SEARCH_SNIPPET_RADIUS) -> str:
    """بخش کوچکی از متن را که شامل عبارت جست‌وجو است برمی‌گرداند."""
    collapsed = " ".join(text.split())
    needle = query.strip()

    if not collapsed or not needle:
        return collapsed

    index = collapsed.casefold().find(needle.casefold())

    if index < 0:
        clipped = collapsed[: radius * 2].rstrip()

        return f"{clipped}…" if len(collapsed) > radius * 2 else clipped

    start = max(0, index - radius)
    end = min(len(collapsed), index + len(needle) + radius)
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(collapsed) else ""

    return f"{prefix}{collapsed[start:end].strip()}{suffix}"


@dataclass(frozen=True)
class Conversation:
    """یک گفتگوی ذخیره‌شده."""

    id: int
    title: str
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class Memory:
    """یک واقعیت ذخیره‌شده درباره کاربر."""

    id: int
    content: str
    enabled: bool
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class Task:
    """یک وظیفه ذخیره‌شده."""

    id: int
    title: str
    done: bool
    priority: str
    created_at: str
    updated_at: str
    due_date: str = ""


@dataclass(frozen=True)
class Note:
    """یک یادداشت ذخیره‌شده."""

    id: int
    title: str
    content: str
    created_at: str
    updated_at: str
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class SearchHit:
    """یک نتیجه جست‌وجوی سراسری در یکی از بخش‌های برنامه."""

    kind: str
    id: int
    title: str
    snippet: str
    updated_at: str


@dataclass(frozen=True)
class StoreStats:
    """آمار کلی پایگاه‌داده برای نمایش در داشبورد."""

    conversation_count: int
    message_count: int
    user_message_count: int
    assistant_message_count: int


class ConversationStore:
    """گفتگوها را در یک پایگاه‌داده SQLite محلی نگه می‌دارد.

    پیام کاربر و پاسخ مدل همیشه با هم ذخیره می‌شوند تا گفتگوی نیمه‌کاره و ناموفق
    در پایگاه‌داده باقی نماند.
    """

    def __init__(self, database_path: Path | str | None = None) -> None:
        self.database_path = (
            Path(database_path) if database_path is not None else DEFAULT_DATABASE_PATH
        )

        if self.database_path.parent != Path(""):
            self.database_path.parent.mkdir(parents=True, exist_ok=True)

        self._connection = sqlite3.connect(self.database_path)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.executescript(SCHEMA)
        self._apply_migrations()
        self._connection.commit()

    def _apply_migrations(self) -> None:
        """ستون‌های تازه را به پایگاه‌داده‌های ساخته‌شده با نسخه‌های قبلی اضافه می‌کند."""
        for table, columns in MIGRATIONS.items():
            existing = self._table_columns(table)

            for column, definition in columns.items():
                if column in existing:
                    continue

                self._connection.execute(
                    f"ALTER TABLE {table} ADD COLUMN {column} {definition}"
                )

    def create_conversation(self, title: str) -> int:
        """گفتگوی تازه می‌سازد و شناسه آن را برمی‌گرداند."""
        timestamp = _timestamp()
        cursor = self._connection.execute(
            "INSERT INTO conversations (title, created_at, updated_at) VALUES (?, ?, ?)",
            (normalise_title(title), timestamp, timestamp),
        )
        self._connection.commit()

        return int(cursor.lastrowid)

    def add_exchange(self, conversation_id: int, user_text: str, assistant_text: str) -> None:
        """پیام کاربر و پاسخ مدل را با هم در یک تراکنش ذخیره می‌کند."""
        timestamp = _timestamp()

        with self._connection:
            self._connection.executemany(
                "INSERT INTO messages (conversation_id, role, content, created_at) "
                "VALUES (?, ?, ?, ?)",
                [
                    (conversation_id, "user", user_text, timestamp),
                    (conversation_id, "assistant", assistant_text, timestamp),
                ],
            )
            self._connection.execute(
                "UPDATE conversations SET updated_at = ? WHERE id = ?",
                (timestamp, conversation_id),
            )

    def load_messages(self, conversation_id: int) -> list[dict[str, str]]:
        """پیام‌های یک گفتگو را به ترتیب ارسال برمی‌گرداند."""
        cursor = self._connection.execute(
            "SELECT role, content FROM messages WHERE conversation_id = ? ORDER BY id",
            (conversation_id,),
        )

        return [
            {"role": row["role"], "content": row["content"]}
            for row in cursor.fetchall()
            if row["role"] in MESSAGE_ROLES
        ]

    def list_conversations(self, limit: int = 40) -> list[Conversation]:
        """گفتگوها را بر پایه تازه‌ترین پیام برمی‌گرداند.

        ترتیب بر پایه شناسه آخرین پیام است تا حتی وقتی چند گفتگو در یک لحظه
        به‌روز می‌شوند نتیجه قطعی بماند.
        """
        cursor = self._connection.execute(
            "SELECT id, title, created_at, updated_at FROM conversations "
            "ORDER BY COALESCE("
            "    (SELECT MAX(messages.id) FROM messages "
            "     WHERE messages.conversation_id = conversations.id), 0) DESC, "
            "    id DESC "
            "LIMIT ?",
            (int(limit),),
        )

        return [
            Conversation(
                id=int(row["id"]),
                title=row["title"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )
            for row in cursor.fetchall()
        ]

    def latest_conversation(self) -> Conversation | None:
        """آخرین گفتگویی که پیام داشته است."""
        conversations = self.list_conversations(limit=1)

        return conversations[0] if conversations else None

    def get_conversation(self, conversation_id: int) -> Conversation | None:
        """یک گفتگو را با شناسه برمی‌گرداند."""
        cursor = self._connection.execute(
            "SELECT id, title, created_at, updated_at FROM conversations WHERE id = ?",
            (conversation_id,),
        )
        row = cursor.fetchone()

        if row is None:
            return None

        return Conversation(
            id=int(row["id"]),
            title=row["title"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def last_message(self, conversation_id: int) -> str | None:
        """متن آخرین پیام یک گفتگو را برمی‌گرداند."""
        cursor = self._connection.execute(
            "SELECT content FROM messages WHERE conversation_id = ? ORDER BY id DESC LIMIT 1",
            (conversation_id,),
        )
        row = cursor.fetchone()

        return row["content"] if row is not None else None

    def stats(self) -> StoreStats:
        """آمار کلی گفتگوها و پیام‌ها را برمی‌گرداند."""
        cursor = self._connection.execute(
            "SELECT "
            "  (SELECT COUNT(*) FROM conversations) AS conversation_count, "
            "  (SELECT COUNT(*) FROM messages) AS message_count, "
            "  (SELECT COUNT(*) FROM messages WHERE role = 'user') AS user_message_count, "
            "  (SELECT COUNT(*) FROM messages WHERE role = 'assistant') "
            "    AS assistant_message_count"
        )
        row = cursor.fetchone()

        return StoreStats(
            conversation_count=int(row["conversation_count"]),
            message_count=int(row["message_count"]),
            user_message_count=int(row["user_message_count"]),
            assistant_message_count=int(row["assistant_message_count"]),
        )

    def delete_conversation(self, conversation_id: int) -> None:
        """یک گفتگو و همه پیام‌هایش را برای همیشه حذف می‌کند."""
        with self._connection:
            self._connection.execute(
                "DELETE FROM messages WHERE conversation_id = ?", (conversation_id,)
            )
            self._connection.execute(
                "DELETE FROM conversations WHERE id = ?", (conversation_id,)
            )

    # ---------------------------------------------------------------- یادداشت‌ها

    def create_note(self, title: str, content: str = "", tags: str = "") -> int:
        """یادداشت تازه می‌سازد و شناسه آن را برمی‌گرداند."""
        timestamp = _timestamp()
        cursor = self._connection.execute(
            "INSERT INTO notes (title, content, tags, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                normalise_title(title, max_length=120),
                content,
                normalise_tags(tags),
                timestamp,
                timestamp,
            ),
        )
        self._connection.commit()

        return int(cursor.lastrowid)

    def update_note(self, note_id: int, title: str, content: str, tags: str = "") -> None:
        """عنوان، متن و برچسب‌های یادداشت را جایگزین می‌کند."""
        self._connection.execute(
            "UPDATE notes SET title = ?, content = ?, tags = ?, updated_at = ? WHERE id = ?",
            (
                normalise_title(title, max_length=120),
                content,
                normalise_tags(tags),
                _timestamp(),
                note_id,
            ),
        )
        self._connection.commit()

    def list_note_tags(self) -> list[tuple[str, int]]:
        """برچسب‌های به‌کاررفته و تعداد یادداشت هر کدام را برمی‌گرداند.

        پربسامدترین برچسب اول می‌آید تا فهرست فیلتر کوتاه و مفید بماند.
        """
        counts: dict[str, int] = {}
        order: list[str] = []

        for note in self.list_notes():
            for tag in note.tags:
                key = tag.casefold()

                if key not in counts:
                    counts[key] = 0
                    order.append(tag)

                counts[key] += 1

        tags = [(tag, counts[tag.casefold()]) for tag in order]
        tags.sort(key=lambda item: -item[1])

        return tags

    def delete_note(self, note_id: int) -> None:
        """یادداشت را حذف می‌کند."""
        self._connection.execute("DELETE FROM notes WHERE id = ?", (note_id,))
        self._connection.commit()

    def get_note(self, note_id: int) -> Note | None:
        """یک یادداشت را با شناسه برمی‌گرداند."""
        cursor = self._connection.execute(
            "SELECT id, title, content, tags, created_at, updated_at FROM notes WHERE id = ?",
            (note_id,),
        )
        row = cursor.fetchone()

        return self._note_from_row(row) if row is not None else None

    def list_notes(self) -> list[Note]:
        """یادداشت‌ها را با تازه‌ترین ویرایش برمی‌گرداند."""
        cursor = self._connection.execute(
            "SELECT id, title, content, tags, created_at, updated_at FROM notes "
            "ORDER BY updated_at DESC, id DESC"
        )

        return [self._note_from_row(row) for row in cursor.fetchall()]

    def count_notes(self) -> int:
        """تعداد یادداشت‌ها را برمی‌گرداند."""
        cursor = self._connection.execute("SELECT COUNT(*) FROM notes")

        return int(cursor.fetchone()[0])

    @staticmethod
    def _note_from_row(row: sqlite3.Row) -> Note:
        """یک سطر پایگاه‌داده را به یادداشت تبدیل می‌کند."""
        return Note(
            id=int(row["id"]),
            title=row["title"],
            content=row["content"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            tags=parse_tags(row["tags"] or ""),
        )

    # -------------------------------------------------------------------- وظایف

    def create_task(
        self,
        title: str,
        priority: str = "normal",
        due_date: str = "",
    ) -> int:
        """وظیفه تازه می‌سازد و شناسه آن را برمی‌گرداند."""
        if priority not in TASK_PRIORITIES:
            raise ValueError(f"اولویت نامعتبر: {priority}")

        timestamp = _timestamp()
        cursor = self._connection.execute(
            "INSERT INTO tasks (title, done, priority, due_date, created_at, updated_at) "
            "VALUES (?, 0, ?, ?, ?, ?)",
            (
                normalise_title(title, max_length=120),
                priority,
                normalise_due_date(due_date),
                timestamp,
                timestamp,
            ),
        )
        self._connection.commit()

        return int(cursor.lastrowid)

    def update_task(
        self,
        task_id: int,
        title: str,
        priority: str = "normal",
        due_date: str = "",
    ) -> None:
        """عنوان، اولویت و موعد وظیفه را جایگزین می‌کند."""
        if priority not in TASK_PRIORITIES:
            raise ValueError(f"اولویت نامعتبر: {priority}")

        self._connection.execute(
            "UPDATE tasks SET title = ?, priority = ?, due_date = ?, updated_at = ? "
            "WHERE id = ?",
            (
                normalise_title(title, max_length=120),
                priority,
                normalise_due_date(due_date),
                _timestamp(),
                task_id,
            ),
        )
        self._connection.commit()

    def set_task_due_date(self, task_id: int, due_date: str) -> None:
        """فقط موعد وظیفه را تغییر می‌دهد."""
        self._connection.execute(
            "UPDATE tasks SET due_date = ?, updated_at = ? WHERE id = ?",
            (normalise_due_date(due_date), _timestamp(), task_id),
        )
        self._connection.commit()

    def set_task_done(self, task_id: int, done: bool) -> None:
        """وضعیت انجام وظیفه را تغییر می‌دهد."""
        self._connection.execute(
            "UPDATE tasks SET done = ?, updated_at = ? WHERE id = ?",
            (1 if done else 0, _timestamp(), task_id),
        )
        self._connection.commit()

    def delete_task(self, task_id: int) -> None:
        """وظیفه را حذف می‌کند."""
        self._connection.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        self._connection.commit()

    def get_task(self, task_id: int) -> Task | None:
        """یک وظیفه را با شناسه برمی‌گرداند."""
        cursor = self._connection.execute(
            "SELECT id, title, done, priority, due_date, created_at, updated_at "
            "FROM tasks WHERE id = ?",
            (task_id,),
        )
        row = cursor.fetchone()

        return self._task_from_row(row) if row is not None else None

    def list_tasks(self, *, include_done: bool = True) -> list[Task]:
        """وظایف را برمی‌گرداند: اول انجام‌نشده‌ها، بعد اولویت، بعد تازگی.

        انجام‌شده‌ها به ترتیب تازه‌ترین ویرایش و انجام‌نشده‌ها به ترتیب قدیمی‌ترین
        می‌آیند تا کارهای در انتظار بالا بمانند.
        """
        query = (
            "SELECT id, title, done, priority, due_date, created_at, updated_at FROM tasks"
        )
        if not include_done:
            query += " WHERE done = 0"

        # وظیفه دارای موعد در انتهای انجام‌نشده‌ها اول می‌آید: نزدیک‌ترین موعد بالا،
        # و کارهای بدون موعد بعد از آن‌ها.
        query += (
            " ORDER BY done ASC, "
            "CASE WHEN done = 0 AND due_date != '' THEN 0 ELSE 1 END ASC, "
            "CASE WHEN done = 0 THEN due_date END ASC, "
            "CASE priority WHEN 'high' THEN 0 WHEN 'normal' THEN 1 ELSE 2 END ASC, "
            "CASE done WHEN 1 THEN updated_at END DESC, "
            "CASE done WHEN 0 THEN created_at END ASC, "
            "id DESC"
        )
        cursor = self._connection.execute(query)

        return [self._task_from_row(row) for row in cursor.fetchall()]

    def count_tasks(self, *, include_done: bool = True) -> int:
        """تعداد وظایف را برمی‌گرداند."""
        if include_done:
            cursor = self._connection.execute("SELECT COUNT(*) FROM tasks")
        else:
            cursor = self._connection.execute("SELECT COUNT(*) FROM tasks WHERE done = 0")

        return int(cursor.fetchone()[0])

    @staticmethod
    def _task_from_row(row: sqlite3.Row) -> Task:
        """یک سطر پایگاه‌داده را به وظیفه تبدیل می‌کند."""
        return Task(
            id=int(row["id"]),
            title=row["title"],
            done=bool(row["done"]),
            priority=row["priority"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            due_date=row["due_date"] or "",
        )

    # --------------------------------------------------------------------- حافظه

    def add_memory(self, content: str) -> int:
        """یک واقعیت تازه درباره کاربر ذخیره می‌کند و شناسه آن را برمی‌گرداند."""
        text = " ".join(content.split())
        if not text:
            raise ValueError("متن حافظه خالی است")

        if len(text) > MAX_MEMORY_CHARS:
            raise ValueError(f"متن حافظه باید حداکثر {MAX_MEMORY_CHARS} نویسه باشد")

        timestamp = _timestamp()
        cursor = self._connection.execute(
            "INSERT INTO memories (content, enabled, created_at, updated_at) "
            "VALUES (?, 1, ?, ?)",
            (text, timestamp, timestamp),
        )
        self._connection.commit()

        return int(cursor.lastrowid)

    def update_memory(self, memory_id: int, content: str) -> None:
        """متن یک واقعیت را جایگزین می‌کند."""
        text = " ".join(content.split())
        if not text:
            raise ValueError("متن حافظه خالی است")

        if len(text) > MAX_MEMORY_CHARS:
            raise ValueError(f"متن حافظه باید حداکثر {MAX_MEMORY_CHARS} نویسه باشد")

        self._connection.execute(
            "UPDATE memories SET content = ?, updated_at = ? WHERE id = ?",
            (text, _timestamp(), memory_id),
        )
        self._connection.commit()

    def set_memory_enabled(self, memory_id: int, enabled: bool) -> None:
        """حافظه را برای تزریق در پرامپت فعال یا غیرفعال می‌کند."""
        self._connection.execute(
            "UPDATE memories SET enabled = ?, updated_at = ? WHERE id = ?",
            (1 if enabled else 0, _timestamp(), memory_id),
        )
        self._connection.commit()

    def delete_memory(self, memory_id: int) -> None:
        """حافظه را حذف می‌کند."""
        self._connection.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
        self._connection.commit()

    def get_memory(self, memory_id: int) -> Memory | None:
        """یک حافظه را با شناسه برمی‌گرداند."""
        cursor = self._connection.execute(
            "SELECT id, content, enabled, created_at, updated_at FROM memories "
            "WHERE id = ?",
            (memory_id,),
        )
        row = cursor.fetchone()

        return self._memory_from_row(row) if row is not None else None

    def list_memories(self, *, only_enabled: bool = False) -> list[Memory]:
        """حافظه‌ها را به ترتیب تازگی برمی‌گرداند."""
        query = "SELECT id, content, enabled, created_at, updated_at FROM memories"
        if only_enabled:
            query += " WHERE enabled = 1"

        query += " ORDER BY id DESC"
        cursor = self._connection.execute(query)

        return [self._memory_from_row(row) for row in cursor.fetchall()]

    def count_memories(self, *, only_enabled: bool = False) -> int:
        """تعداد حافظه‌ها را برمی‌گرداند."""
        if only_enabled:
            cursor = self._connection.execute(
                "SELECT COUNT(*) FROM memories WHERE enabled = 1"
            )
        else:
            cursor = self._connection.execute("SELECT COUNT(*) FROM memories")

        return int(cursor.fetchone()[0])

    @staticmethod
    def _memory_from_row(row: sqlite3.Row) -> Memory:
        """یک سطر پایگاه‌داده را به حافظه تبدیل می‌کند."""
        return Memory(
            id=int(row["id"]),
            content=row["content"],
            enabled=bool(row["enabled"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    # ----------------------------------------------------------- جست‌وجو

    def search(
        self,
        query: str,
        *,
        limit_per_kind: int = SEARCH_LIMIT_PER_KIND,
    ) -> list[SearchHit]:
        """در گفتگو، پیام، یادداشت، وظیفه و حافظه جست‌وجو می‌کند.

        نتیجه‌ها به ترتیب بخش‌ها برمی‌گردند و هر بخش حداکثر `limit_per_kind` نتیجه
        دارد تا فهرست کوتاه و قابل مرور بماند.
        """
        text = query.strip()

        if not text:
            return []

        pattern = _like_pattern(text)
        limit = max(1, int(limit_per_kind))

        hits = [
            *self._search_conversations(pattern, text, limit),
            *self._search_notes(pattern, text, limit),
            *self._search_tasks(pattern, text, limit),
            *self._search_memories(pattern, text, limit),
        ]

        return hits

    def _search_conversations(self, pattern: str, text: str, limit: int) -> list[SearchHit]:
        """جست‌وجو در عنوان گفتگوها و متن پیام‌ها (هر گفتگو یک نتیجه)."""
        cursor = self._connection.execute(
            "SELECT conversations.id AS conversation_id, conversations.title, "
            "       conversations.updated_at, "
            "       (SELECT messages.content FROM messages "
            "        WHERE messages.conversation_id = conversations.id "
            "          AND messages.content LIKE ? ESCAPE '\\' "
            "        ORDER BY messages.id LIMIT 1) AS snippet "
            "FROM conversations "
            "WHERE conversations.title LIKE ? ESCAPE '\\' "
            "   OR EXISTS (SELECT 1 FROM messages WHERE messages.conversation_id = conversations.id "
            "              AND messages.content LIKE ? ESCAPE '\\') "
            "ORDER BY COALESCE("
            "    (SELECT MAX(messages.id) FROM messages "
            "     WHERE messages.conversation_id = conversations.id), 0) DESC, "
            "    conversations.id DESC "
            "LIMIT ?",
            (pattern, pattern, pattern, limit),
        )

        return [
            SearchHit(
                kind="conversation",
                id=int(row["conversation_id"]),
                title=row["title"],
                snippet=snippet_from(row["snippet"] or row["title"], text),
                updated_at=row["updated_at"],
            )
            for row in cursor.fetchall()
        ]

    def _search_notes(self, pattern: str, text: str, limit: int) -> list[SearchHit]:
        """جست‌وجو در عنوان و متن یادداشت‌ها."""
        cursor = self._connection.execute(
            "SELECT id, title, content, tags, updated_at FROM notes "
            "WHERE title LIKE ? ESCAPE '\\' OR content LIKE ? ESCAPE '\\' "
            "   OR tags LIKE ? ESCAPE '\\' "
            "ORDER BY updated_at DESC, id DESC LIMIT ?",
            (pattern, pattern, pattern, limit),
        )

        return [
            SearchHit(
                kind="note",
                id=int(row["id"]),
                title=row["title"],
                snippet=self._note_snippet(row, text),
                updated_at=row["updated_at"],
            )
            for row in cursor.fetchall()
        ]

    @staticmethod
    def _note_snippet(row: sqlite3.Row, text: str) -> str:
        """نمونه متن یادداشت را می‌سازد.

        اگر عبارت جست‌وجو فقط در برچسب‌ها پیدا شده باشد، پیش از متن یادداشت،
        برچسب‌ها نشان داده می‌شوند تا نتیجه بی‌ربط به نظر نرسد.
        """
        content = row["content"] or ""
        tags = row["tags"] or ""

        if text.casefold() in content.casefold() or not tags:
            return snippet_from(content or row["title"], text)

        return f"برچسب: {tags} — {snippet_from(content or row['title'], text)}"

    def _search_tasks(self, pattern: str, text: str, limit: int) -> list[SearchHit]:
        """جست‌وجو در عنوان وظیفه‌ها."""
        cursor = self._connection.execute(
            "SELECT id, title, done, priority, due_date, updated_at FROM tasks "
            "WHERE title LIKE ? ESCAPE '\\' "
            "ORDER BY done, id DESC LIMIT ?",
            (pattern, limit),
        )

        return [
            SearchHit(
                kind="task",
                id=int(row["id"]),
                title=row["title"],
                snippet=self._task_snippet(row),
                updated_at=row["updated_at"],
            )
            for row in cursor.fetchall()
        ]

    @staticmethod
    def _task_snippet(row: sqlite3.Row) -> str:
        """نمونه متن وظیفه: وضعیت، اولویت و موعد."""
        parts = [
            "انجام‌شده"
            if row["done"]
            else "در انتظار",
            TASK_PRIORITY_LABELS.get(row["priority"], row["priority"]),
        ]

        if row["due_date"]:
            parts.append(f"موعد: {row['due_date']}")

        return " • ".join(parts)

    def _search_memories(self, pattern: str, text: str, limit: int) -> list[SearchHit]:
        """جست‌وجو در واقعیت‌های ذخیره‌شده درباره کاربر."""
        cursor = self._connection.execute(
            "SELECT id, content, enabled, updated_at FROM memories "
            "WHERE content LIKE ? ESCAPE '\\' "
            "ORDER BY enabled DESC, id DESC LIMIT ?",
            (pattern, limit),
        )

        return [
            SearchHit(
                kind="memory",
                id=int(row["id"]),
                title=snippet_from(row["content"], text),
                snippet="فعال" if row["enabled"] else "غیرفعال",
                updated_at=row["updated_at"],
            )
            for row in cursor.fetchall()
        ]

    # ----------------------------------------------------------- پشتیبان‌گیری

    def snapshot(self) -> dict[str, list[dict[str, object]]]:
        """همه ردیف‌های جدول‌های داده را برای پشتیبان‌گیری برمی‌گرداند."""
        snapshot: dict[str, list[dict[str, object]]] = {}

        for table in BACKUP_TABLES:
            cursor = self._connection.execute(f"SELECT * FROM {table}")
            snapshot[table] = [dict(row) for row in cursor.fetchall()]

        return snapshot

    def restore(
        self,
        snapshot: Mapping[str, Sequence[Mapping[str, object]]],
        *,
        replace: bool = True,
    ) -> dict[str, int]:
        """داده‌های پشتیبان را وارد پایگاه‌داده می‌کند و تعداد ردیف‌ها را برمی‌گرداند.

        کل عمل در یک تراکنش انجام می‌شود؛ اگر ردیفی نامعتبر باشد هیچ تغییری باقی
        نمی‌ماند. با `replace=True` داده‌های فعلی پاک می‌شوند.
        """
        counts: dict[str, int] = {}

        with self._connection:
            if replace:
                # ترتیب حذف برعکس ترتیب درج است تا کلید خارجی نشکند.
                for table in reversed(BACKUP_TABLES):
                    self._connection.execute(f"DELETE FROM {table}")

            for table in BACKUP_TABLES:
                columns = self._table_columns(table)
                rows = [row for row in snapshot.get(table, []) if isinstance(row, Mapping)]
                inserted = 0

                for row in rows:
                    values = {key: value for key, value in row.items() if key in columns}

                    if not values:
                        continue

                    placeholders = ", ".join("?" for _ in values)
                    self._connection.execute(
                        f"INSERT INTO {table} ({', '.join(values)}) VALUES ({placeholders})",
                        list(values.values()),
                    )
                    inserted += 1

                counts[table] = inserted

        return counts

    def _table_columns(self, table: str) -> set[str]:
        """نام ستون‌های یک جدول را از خود SQLite می‌خواند."""
        cursor = self._connection.execute(f"PRAGMA table_info({table})")

        return {row["name"] for row in cursor.fetchall()}

    def close(self) -> None:
        """اتصال پایگاه‌داده را می‌بندد."""
        self._connection.close()
