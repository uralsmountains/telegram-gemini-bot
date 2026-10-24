import os
import re
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

from aiogram import Router, F
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message,
    CallbackQuery,
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardRemove
)

import database
from ai_assistant import ask_ai

router = Router()

def get_now() -> datetime:
    """Возвращает текущее время с учетом часового пояса (по умолчанию UTC+5)."""
    offset_hours = int(os.getenv("TIMEZONE_OFFSET", "5"))
    tz = timezone(timedelta(hours=offset_hours))
    return datetime.now(tz).replace(tzinfo=None)

# Состояния FSM
class ReminderForm(StatesGroup):
    waiting_for_text = State()
    waiting_for_time = State()

# Главное меню (Reply-кнопки)
def get_main_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="➕ Создать напоминание")],
            [KeyboardButton(text="📋 Мои напоминания"), KeyboardButton(text="❓ Справка")]
        ],
        resize_keyboard=True
    )

# Клавиатура выбора времени
def get_quick_time_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="⏱ Через 10 мин", callback_data="time_10m"),
                InlineKeyboardButton(text="⏱ Через 30 мин", callback_data="time_30m"),
            ],
            [
                InlineKeyboardButton(text="⏱ Через 1 час", callback_data="time_1h"),
                InlineKeyboardButton(text="⏱ Через 3 часа", callback_data="time_3h"),
            ],
            [
                InlineKeyboardButton(text="🌙 Сегодня в 20:00", callback_data="time_today_20"),
                InlineKeyboardButton(text="☀️ Завтра в 09:00", callback_data="time_tomorrow_09"),
            ],
            [
                InlineKeyboardButton(text="🔁 Каждый день в 09:00", callback_data="repeat_daily_09"),
            ],
            [
                InlineKeyboardButton(text="✏️ Ввести своё время", callback_data="custom_time_prompt"),
            ],
            [
                InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_action"),
            ]
        ]
    )

def parse_smart_time(text: str, now: datetime) -> Tuple[Optional[datetime], Optional[str]]:
    """
    Интеллектуальный парсер даты и времени:
    - Относительное: '10m', '10м', 'через 15 минут', 'через 2 часа', 'через 1 день'
    - Точное время: '18:30', '18.30', 'в 18:30', 'сегодня в 18:30'
    - Завтра / послезавтра: 'завтра в 10:00', 'завтра 14:30', 'послезавтра в 12:00'
    - Конкретная дата: '25.10 15:00', '25.10 в 15:00', '25.10.2026 15:00'
    - Повторяющееся: 'каждый день в 09:00', 'ежедневно в 18:30'
    """
    text = text.strip().lower()
    text = re.sub(r'\s+', ' ', text)

    # 1. Повторяющееся: "каждый день в HH:MM" / "ежедневно в HH:MM"
    m = re.match(r'^(?:каждый\s+день|ежедневно)(?:\s+в)?\s+(\d{1,2})[:\.](\d{2})$', text)
    if m:
        h, mn = int(m.group(1)), int(m.group(2))
        if 0 <= h < 24 and 0 <= mn < 60:
            target = now.replace(hour=h, minute=mn, second=0, microsecond=0)
            if target <= now:
                target += timedelta(days=1)
            return target, "daily"

    # 2. Относительное: "через 15 минут", "15м", "через 2 часа", "2ч", "1д"
    m = re.match(r'^(?:через\s+)?(\d+)\s*(m|мин|минут|минуты|минуту|h|ч|час|часа|часов|d|д|день|дня|дней)$', text)
    if m:
        val = int(m.group(1))
        unit = m.group(2)
        if unit.startswith(('m', 'мин')):
            return now + timedelta(minutes=val), None
        elif unit.startswith(('h', 'ч', 'час')):
            return now + timedelta(hours=val), None
        elif unit.startswith(('d', 'д')):
            return now + timedelta(days=val), None

    # 3. "завтра в HH:MM" или "завтра HH:MM"
    m = re.match(r'^завтра(?:\s+в)?\s+(\d{1,2})[:\.](\d{2})$', text)
    if m:
        h, mn = int(m.group(1)), int(m.group(2))
        if 0 <= h < 24 and 0 <= mn < 60:
            target = (now + timedelta(days=1)).replace(hour=h, minute=mn, second=0, microsecond=0)
            return target, None

    # 4. "послезавтра в HH:MM"
    m = re.match(r'^послезавтра(?:\s+в)?\s+(\d{1,2})[:\.](\d{2})$', text)
    if m:
        h, mn = int(m.group(1)), int(m.group(2))
        if 0 <= h < 24 and 0 <= mn < 60:
            target = (now + timedelta(days=2)).replace(hour=h, minute=mn, second=0, microsecond=0)
            return target, None

    # 5. "сегодня в HH:MM", "в HH:MM", "HH:MM", "HH.MM"
    m = re.match(r'^(?:сегодня\s+)?(?:в\s+)?(\d{1,2})[:\.](\d{2})$', text)
    if m:
        h, mn = int(m.group(1)), int(m.group(2))
        if 0 <= h < 24 and 0 <= mn < 60:
            target = now.replace(hour=h, minute=mn, second=0, microsecond=0)
            if target <= now:
                target += timedelta(days=1)
            return target, None

    # 6. Дата "DD.MM[.YYYY] (в)? HH:MM"
    m = re.match(r'^(\d{1,2})\.(\d{1,2})(?:\.(\d{4}))?(?:\s+в|\s+)\s*(\d{1,2})[:\.](\d{2})$', text)
    if m:
        day, month = int(m.group(1)), int(m.group(2))
        year = int(m.group(3)) if m.group(3) else now.year
        h, mn = int(m.group(4)), int(m.group(5))
        try:
            target = datetime(year, month, day, h, mn)
            if not m.group(3) and target <= now:
                target = datetime(year + 1, month, day, h, mn)
            return target, None
        except ValueError:
            return None, None

    return None, None

# --- Команды ---

@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "👋 <b>Привет! Я ваш умный бот-помощник с ИИ и напоминаниями.</b>\n\n"
        "🤖 <b>Что я умею:</b>\n"
        "• <b>Умный ИИ-ассистент:</b> просто напишите мне любой вопрос в чат — я отвечу с актуальными знаниями из Google!\n"
        "• <b>Напоминания:</b> нажмите <b>«➕ Создать напоминание»</b> или используйте быструю команду:\n"
        "  <code>/remind через 2 часа проверить почту</code>\n"
        "  <code>/remind завтра в 10:00 созвон</code>\n"
        "• <b>«📋 Мои напоминания»</b> — список ваших дел с удалением в один клик.",
        parse_mode="HTML",
        reply_markup=get_main_keyboard()
    )

@router.message(Command("help"))
@router.message(F.text == "❓ Справка")
async def cmd_help(message: Message):
    now = get_now()
    help_text = (
        "📖 <b>Как задавать время напоминания:</b>\n\n"
        "Вы можете вводить своё время <b>в свободной форме</b> текстом:\n\n"
        "⏰ <b>Относительное время:</b>\n"
        "• <code>через 15 минут</code>, <code>через 40 минут</code>\n"
        "• <code>через 2 часа</code>, <code>через 5 часов</code>\n"
        "• <code>через 1 день</code>\n"
        "• Или кратко: <code>15м</code>, <code>30m</code>, <code>2ч</code>, <code>1д</code>\n\n"
        "📅 <b>Точное время:</b>\n"
        "• <code>18:30</code> или <code>в 18:30</code> (если время уже прошло — перенесется на завтра)\n"
        "• <code>сегодня в 21:00</code>\n"
        "• <code>завтра в 09:00</code>\n"
        "• <code>послезавтра в 15:00</code>\n"
        "• <code>26.10 в 14:30</code>\n\n"
        "🔁 <b>Повторяющиеся напоминания:</b>\n"
        "• <code>каждый день в 09:00</code>\n"
        "• <code>ежедневно в 20:00</code>\n\n"
        f"<i>Текущее время бота: {now.strftime('%d.%m.%Y %H:%M')}</i>"
    )
    await message.answer(help_text, parse_mode="HTML")

@router.message(Command("cancel"))
@router.message(F.text.lower() == "отмена")
async def cmd_cancel(message: Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state is None:
        await message.answer("Нечего отменять.", reply_markup=get_main_keyboard())
        return
    await state.clear()
    await message.answer("Действие отменено.", reply_markup=get_main_keyboard())

# --- Умная быстрая команда /remind ---

@router.message(Command("remind"))
async def cmd_remind_quick(message: Message):
    text_content = message.text.replace("/remind", "", 1).strip()
    if not text_content:
        await message.answer(
            "⚠️ <b>Формат команды:</b> <code>/remind [время] [текст]</code>\n\n"
            "Примеры:\n"
            "• <code>/remind через 30 минут выключить духовку</code>\n"
            "• <code>/remind завтра в 10:00 совещание</code>\n"
            "• <code>/remind 18:30 сходить в спортзал</code>\n"
            "• <code>/remind 26.10 в 14:00 врач</code>",
            parse_mode="HTML"
        )
        return

    now = get_now()
    words = text_content.split()
    matched_time = None
    matched_repeat = None
    remind_text = None

    # Проверяем префиксы от 5 слов до 1 слова для поиска выражения времени
    for word_count in range(min(5, len(words) - 1), 0, -1):
        candidate_time_str = " ".join(words[:word_count])
        remind_at, repeat = parse_smart_time(candidate_time_str, now)
        if remind_at:
            matched_time = remind_at
            matched_repeat = repeat
            remind_text = " ".join(words[word_count:])
            break

    if not matched_time or not remind_text:
        await message.answer(
            "⚠️ Не удалось распознать время и текст.\n"
            "Пример: <code>/remind завтра в 11:00 созвон</code> или <code>/remind через 20 минут чай</code>\n"
            "Подробнее в разделе <b>❓ Справка</b>.",
            parse_mode="HTML"
        )
        return

    rem_id = await database.add_reminder(message.from_user.id, remind_text, matched_time, matched_repeat)
    time_formatted = matched_time.strftime("%d.%m.%Y в %H:%M")
    rep_text = " (🔁 каждый день)" if matched_repeat == "daily" else ""
    await message.answer(
        f"✅ <b>Напоминание создано!</b> (ID: {rem_id})\n\n"
        f"📝 <b>Текст:</b> {remind_text}\n"
        f"⏰ <b>Время:</b> {time_formatted}{rep_text}",
        parse_mode="HTML"
    )

# --- Список напоминаний ---

@router.message(Command("list"))
@router.message(F.text == "📋 Мои напоминания")
async def cmd_list(message: Message):
    reminders = await database.get_user_reminders(message.from_user.id)
    if not reminders:
        await message.answer("📭 У вас пока нет активных напоминаний.", reply_markup=get_main_keyboard())
        return

    response = ["📋 <b>Ваши активные напоминания:</b>\n"]
    keyboard_buttons = []

    for rem_id, text, remind_at_str, repeat in reminders:
        repeat_info = " (🔁 ежедневно)" if repeat == "daily" else ""
        response.append(f"• <b>{remind_at_str}</b>{repeat_info}: {text}")
        keyboard_buttons.append([
            InlineKeyboardButton(text=f"🗑 Удалить: {text[:22]}", callback_data=f"del_{rem_id}")
        ])

    kb = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
    await message.answer("\n".join(response), parse_mode="HTML", reply_markup=kb)

@router.callback_query(F.data.startswith("del_"))
async def callback_delete_reminder(callback: CallbackQuery):
    rem_id = int(callback.data.split("_")[1])
    success = await database.delete_reminder(rem_id, callback.from_user.id)
    if success:
        await callback.answer("Напоминание удалено!")
        await callback.message.edit_text("✅ Напоминание успешно удалено.")
    else:
        await callback.answer("Напоминание не найдено или уже удалено.", show_alert=True)

# --- Пошаговый диалог ---

@router.message(F.text == "➕ Создать напоминание")
async def start_reminder_creation(message: Message, state: FSMContext):
    await state.set_state(ReminderForm.waiting_for_text)
    await message.answer(
        "📝 <b>О чем вам напомнить?</b>\n\n"
        "Напишите текст напоминания (для отмены отправьте /cancel):",
        reply_markup=ReplyKeyboardRemove(),
        parse_mode="HTML"
    )

@router.message(ReminderForm.waiting_for_text)
async def process_reminder_text(message: Message, state: FSMContext):
    await state.update_data(reminder_text=message.text)
    await state.set_state(ReminderForm.waiting_for_time)
    await message.answer(
        "⏰ <b>Когда вам напомнить?</b>\n\n"
        "• Выберите быстрый вариант кнопкой ниже\n"
        "• Либо нажмите <b>«✏️ Ввести своё время»</b> / просто напишите время текстом в чат\n"
        "  (например: <code>через 45 минут</code>, <code>завтра в 14:00</code>, <code>19:30</code>, <code>26.10 в 11:00</code>):",
        reply_markup=get_quick_time_keyboard(),
        parse_mode="HTML"
    )

@router.callback_query(ReminderForm.waiting_for_time, F.data == "custom_time_prompt")
async def callback_custom_time_prompt(callback: CallbackQuery):
    await callback.message.answer(
        "✍️ <b>Напишите своё время в ответном сообщении:</b>\n\n"
        "Примеры:\n"
        "• <code>через 45 минут</code> или <code>через 3 часа</code>\n"
        "• <code>19:30</code> (сегодня)\n"
        "• <code>завтра в 10:00</code>\n"
        "• <code>послезавтра в 12:00</code>\n"
        "• <code>26.10 в 15:30</code>\n"
        "• <code>каждый день в 08:30</code>\n\n"
        "<i>Для отмены нажмите /cancel</i>",
        parse_mode="HTML"
    )
    await callback.answer()

@router.callback_query(ReminderForm.waiting_for_time, F.data.startswith("time_"))
async def process_time_button(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    remind_text = data.get("reminder_text", "Без текста")
    now = get_now()
    remind_at = None

    if callback.data == "time_10m":
        remind_at = now + timedelta(minutes=10)
    elif callback.data == "time_30m":
        remind_at = now + timedelta(minutes=30)
    elif callback.data == "time_1h":
        remind_at = now + timedelta(hours=1)
    elif callback.data == "time_3h":
        remind_at = now + timedelta(hours=3)
    elif callback.data == "time_today_20":
        remind_at = now.replace(hour=20, minute=0, second=0, microsecond=0)
        if remind_at <= now:
            remind_at += timedelta(days=1)
    elif callback.data == "time_tomorrow_09":
        remind_at = (now + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)

    if remind_at:
        await database.add_reminder(callback.from_user.id, remind_text, remind_at, None)
        await state.clear()
        time_formatted = remind_at.strftime("%d.%m.%Y в %H:%M")
        await callback.message.edit_text(
            f"✅ <b>Напоминание создано!</b>\n\n"
            f"📝 <b>Текст:</b> {remind_text}\n"
            f"⏰ <b>Время:</b> {time_formatted}",
            parse_mode="HTML"
        )
        await callback.message.answer("Главное меню:", reply_markup=get_main_keyboard())
    await callback.answer()

@router.callback_query(ReminderForm.waiting_for_time, F.data == "repeat_daily_09")
async def process_repeat_daily(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    remind_text = data.get("reminder_text", "Без текста")
    now = get_now()
    remind_at = now.replace(hour=9, minute=0, second=0, microsecond=0)
    if remind_at <= now:
        remind_at += timedelta(days=1)

    await database.add_reminder(callback.from_user.id, remind_text, remind_at, repeat_interval="daily")
    await state.clear()
    await callback.message.edit_text(
        f"✅ <b>Ежедневное напоминание создано!</b>\n\n"
        f"📝 <b>Текст:</b> {remind_text}\n"
        f"⏰ <b>Период:</b> Каждый день в 09:00",
        parse_mode="HTML"
    )
    await callback.message.answer("Главное меню:", reply_markup=get_main_keyboard())
    await callback.answer()

@router.callback_query(F.data == "cancel_action")
async def callback_cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("❌ Создание напоминания отменено.")
    await callback.message.answer("Главное меню:", reply_markup=get_main_keyboard())
    await callback.answer()

@router.message(ReminderForm.waiting_for_time)
async def process_custom_time_text(message: Message, state: FSMContext):
    now = get_now()
    remind_at, repeat = parse_smart_time(message.text, now)
    if not remind_at:
        await message.answer(
            "⚠️ Не удалось распознать время.\n\n"
            "Пожалуйста, напишите в одном из понятных форматов:\n"
            "• <code>через 25 минут</code> или <code>через 2 часа</code>\n"
            "• <code>18:30</code> (сегодня)\n"
            "• <code>завтра в 10:00</code>\n"
            "• <code>26.10 в 14:00</code>\n"
            "• <code>каждый день в 09:00</code>\n\n"
            "Или отправьте /cancel для отмены.",
            parse_mode="HTML"
        )
        return

    data = await state.get_data()
    remind_text = data.get("reminder_text", "Без текста")
    await database.add_reminder(message.from_user.id, remind_text, remind_at, repeat)
    await state.clear()

    time_formatted = remind_at.strftime("%d.%m.%Y в %H:%M")
    rep_text = " (🔁 ежедневно)" if repeat == "daily" else ""
    await message.answer(
        f"✅ <b>Напоминание создано!</b>\n\n"
        f"📝 <b>Текст:</b> {remind_text}\n"
        f"⏰ <b>Время:</b> {time_formatted}{rep_text}",
        parse_mode="HTML",
        reply_markup=get_main_keyboard()
    )

# --- ИИ-ассистент (Gemini) ---

@router.message(Command("ai"))
async def cmd_ai_handler(message: Message):
    query = message.text.replace("/ai", "", 1).strip()
    if not query:
        await message.answer("💡 Задайте вопрос после команды, например:\n<code>/ai Какая сегодня погода в Москве?</code>", parse_mode="HTML")
        return
    await handle_ai_query(message, query)

@router.message(F.text)
async def default_ai_handler(message: Message, state: FSMContext):
    # Если пользователь находится в процессе создания напоминания, не перехватываем
    current_state = await state.get_state()
    if current_state is not None:
        return

    # Пропускаем стандартные кнопки и команды
    if message.text in ["➕ Создать напоминание", "📋 Мои напоминания", "❓ Справка", "/start", "/help", "/cancel"]:
        return

    await handle_ai_query(message, message.text)

async def handle_ai_query(message: Message, query: str):
    await message.bot.send_chat_action(chat_id=message.chat.id, action="typing")
    answer = await ask_ai(query)

    # Лимит одного сообщения Telegram — 4096 символов
    if len(answer) <= 4000:
        try:
            await message.answer(answer, parse_mode="Markdown")
        except Exception:
            await message.answer(answer)
    else:
        for i in range(0, len(answer), 4000):
            chunk = answer[i:i+4000]
            try:
                await message.answer(chunk, parse_mode="Markdown")
            except Exception:
                await message.answer(chunk)
