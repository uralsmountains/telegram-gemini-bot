import os
import json
import logging
from datetime import datetime, timezone, timedelta
import aiohttp

logger = logging.getLogger(__name__)

CACHED_MODEL = None

def get_now() -> datetime:
    offset_hours = int(os.getenv("TIMEZONE_OFFSET", "5"))
    tz = timezone(timedelta(hours=offset_hours))
    return datetime.now(tz).replace(tzinfo=None)

def clean_response(text: str) -> str:
    """Очищает ответ от возможных рассуждений ИИ вслух и черновиков."""
    if "*Drafting the response:*" in text:
        text = text.split("*Drafting the response:*")[-1].strip()
    elif "Drafting:" in text:
        text = text.split("Drafting:")[-1].strip()
    elif "Draft:" in text:
        text = text.split("Draft:")[-1].strip()

    # Убираем случайные кавычки по краям
    text = text.strip().strip('"').strip("'").strip()
    return text

async def get_best_model(session: aiohttp.ClientSession, api_key: str, headers: dict) -> list:
    """Динамически запрашивает список доступных моделей у Google."""
    global CACHED_MODEL
    candidates = []
    if CACHED_MODEL:
        candidates.append(CACHED_MODEL)

    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
        async with session.get(url, headers=headers, timeout=10) as resp:
            if resp.status == 200:
                data = await resp.json()
                for m in data.get("models", []):
                    if "generateContent" in m.get("supportedGenerationMethods", []):
                        name = m["name"].replace("models/", "")
                        candidates.append(name)
    except Exception as e:
        logger.warning(f"Ошибка получения списка моделей: {e}")

    fallback_defaults = [
        "gemini-1.5-flash",
        "gemini-2.0-flash",
        "gemini-1.5-pro",
        "gemini-2.0-flash-exp"
    ]
    for d in fallback_defaults:
        if d not in candidates:
            candidates.append(d)

    return candidates

async def ask_ai(prompt: str) -> str:
    """Отправляет запрос к Google Gemini с передачей точной актуальной даты."""
    global CACHED_MODEL
    raw_key = os.getenv("GEMINI_API_KEY", "")
    api_key = raw_key.strip().strip('"').strip("'")

    if not api_key:
        return "⚠️ Переменная GEMINI_API_KEY не найдена на сервере Render."

    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": api_key
    }

    # Формируем актуальную дату на русском
    now_dt = get_now()
    months_ru = [
        "января", "февраля", "марта", "апреля", "мая", "июня",
        "июля", "августа", "сентября", "октября", "ноября", "декабря"
    ]
    cur_date_str = f"{now_dt.day} {months_ru[now_dt.month - 1]} {now_dt.year} года, {now_dt.strftime('%H:%M')}"

    system_instruction = (
        f"Ты умный, полезный и дружелюбный русскоязычный ИИ-ассистент в Telegram.\n"
        f"ТОЧНАЯ ТЕКУЩАЯ ДАТА И ВРЕМЯ ПОЛЬЗОВАТЕЛЯ: {cur_date_str}.\n"
        "ВАЖНЫЕ ПРАВИЛА:\n"
        "1. Отвечай СРАЗУ готовым финальным текстом для пользователя на русском языке.\n"
        "2. СТРОГО ЗАПРЕЩЕНО выводить рассуждения, внутренние размышления, анализ вопроса или черновики (Drafting).\n"
        "3. Отвечай четко, емко и по существу."
    )

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "systemInstruction": {"parts": [{"text": system_instruction}]}
    }

    last_error_text = ""

    async with aiohttp.ClientSession() as session:
        models_to_try = await get_best_model(session, api_key, headers)

        for model in models_to_try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
            try:
                async with session.post(url, headers=headers, json=payload, timeout=25) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        candidates = data.get("candidates", [])
                        if candidates:
                            parts = candidates[0].get("content", {}).get("parts", [])
                            texts = [p.get("text", "") for p in parts if "text" in p]
                            if texts:
                                CACHED_MODEL = model
                                return clean_response("\n".join(texts))
                    else:
                        err_body = await resp.text()
                        logger.warning(f"Модель {model} вернула {resp.status}: {err_body}")
                        last_error_text = err_body
            except Exception as e:
                logger.warning(f"Ошибка запроса к {model}: {e}")
                last_error_text = str(e)

    try:
        err_json = json.loads(last_error_text)
        msg = err_json.get("error", {}).get("message", last_error_text)
        return f"⚠️ Ошибка Gemini: {msg}"
    except Exception:
        return f"⚠️ Ошибка Gemini: {last_error_text[:200]}"
