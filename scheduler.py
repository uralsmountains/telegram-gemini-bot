import logging
from datetime import datetime, timedelta
from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from database import get_due_reminders, mark_completed, update_remind_time

logger = logging.getLogger(__name__)

async def check_reminders(bot: Bot):
    """Периодическая проверка и отправка сработавших напоминаний."""
    try:
        due = await get_due_reminders()
        for reminder_id, user_id, text, remind_at_str, repeat in due:
            msg = f"🔔 <b>Напоминание!</b>\n\n{text}"
            try:
                await bot.send_message(chat_id=user_id, text=msg, parse_mode="HTML")
            except Exception as e:
                logger.error(f"Не удалось отправить напоминание {reminder_id} пользователю {user_id}: {e}")

            # Если напоминание повторяющееся, сдвигаем время на следующий период
            if repeat == "daily":
                current_time = datetime.strptime(remind_at_str, "%Y-%m-%d %H:%M:%S")
                next_time = current_time + timedelta(days=1)
                await update_remind_time(reminder_id, next_time)
            elif repeat == "hourly":
                current_time = datetime.strptime(remind_at_str, "%Y-%m-%d %H:%M:%S")
                next_time = current_time + timedelta(hours=1)
                await update_remind_time(reminder_id, next_time)
            else:
                await mark_completed(reminder_id)
    except Exception as e:
        logger.error(f"Ошибка при обработке напоминаний: {e}")

def setup_scheduler(bot: Bot) -> AsyncIOScheduler:
    """Создание и настройка фонового планировщика задач."""
    scheduler = AsyncIOScheduler()
    scheduler.add_job(check_reminders, "interval", seconds=15, args=[bot])
    return scheduler
