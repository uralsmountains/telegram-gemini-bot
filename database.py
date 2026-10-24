import os
import aiosqlite
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Tuple

if os.path.exists("/data"):
    DB_NAME = "/data/reminders.db"
else:
    DB_NAME = "reminders.db"

def get_now() -> datetime:
    offset_hours = int(os.getenv("TIMEZONE_OFFSET", "5"))
    tz = timezone(timedelta(hours=offset_hours))
    return datetime.now(tz).replace(tzinfo=None)

async def init_db():
    """Инициализация базы данных и создание таблиц."""
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                text TEXT NOT NULL,
                remind_at TEXT NOT NULL,
                repeat_interval TEXT DEFAULT NULL,
                is_completed INTEGER DEFAULT 0,
                created_at TEXT NOT NULL
            )
        """)
        await db.commit()

async def add_reminder(user_id: int, text: str, remind_at: datetime, repeat_interval: Optional[str] = None) -> int:
    """Добавление нового напоминания в базу."""
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute(
            """
            INSERT INTO reminders (user_id, text, remind_at, repeat_interval, is_completed, created_at)
            VALUES (?, ?, ?, ?, 0, ?)
            """,
            (
                user_id,
                text,
                remind_at.strftime("%Y-%m-%d %H:%M:%S"),
                repeat_interval,
                get_now().strftime("%Y-%m-%d %H:%M:%S")
            )
        )
        await db.commit()
        return cursor.lastrowid

async def get_user_reminders(user_id: int) -> List[Tuple]:
    """Получение всех активных напоминаний пользователя."""
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute(
            """
            SELECT id, text, remind_at, repeat_interval
            FROM reminders
            WHERE user_id = ? AND is_completed = 0
            ORDER BY remind_at ASC
            """,
            (user_id,)
        ) as cursor:
            return await cursor.fetchall()

async def get_due_reminders() -> List[Tuple]:
    """Получение напоминаний, время которых уже наступило."""
    now_str = get_now().strftime("%Y-%m-%d %H:%M:%S")
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute(
            """
            SELECT id, user_id, text, remind_at, repeat_interval
            FROM reminders
            WHERE is_completed = 0 AND remind_at <= ?
            """,
            (now_str,)
        ) as cursor:
            return await cursor.fetchall()

async def mark_completed(reminder_id: int):
    """Пометить напоминание как выполненное."""
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "UPDATE reminders SET is_completed = 1 WHERE id = ?",
            (reminder_id,)
        )
        await db.commit()

async def update_remind_time(reminder_id: int, new_time: datetime):
    """Обновить время для повторяющегося напоминания."""
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "UPDATE reminders SET remind_at = ? WHERE id = ?",
            (new_time.strftime("%Y-%m-%d %H:%M:%S"), reminder_id)
        )
        await db.commit()

async def delete_reminder(reminder_id: int, user_id: int) -> bool:
    """Удалить напоминание пользователя."""
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute(
            "DELETE FROM reminders WHERE id = ? AND user_id = ?",
            (reminder_id, user_id)
        )
        await db.commit()
        return cursor.rowcount > 0
