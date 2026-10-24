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
    """Очищает ответ от технических рассуждений и черновиков ИИ."""
    lines = text.strip().split("\n")
    cleaned = []
    is_meta = False

    for line in lines:
        s = line.strip()
        # Признаки мета-рассуждений ИИ
        meta_triggers = [
            "*   Role:", "* Role:", "User asks:", "User Intent:", "Constraint:",
            "Input:", "Drafting", "Option 1:", "Option 2:", "Option 3:",
            "*   Context:", "* Context:", "Scenario A:", "Scenario B:"
        ]
        if any(trigger in s for trigger in meta_triggers) or (s.startswith("*   ") and ":" in s):
            is_meta = True
            continue
        if is_meta and (not s or s.startswith("*") or s.startswith("Option") or s.startswith("Draft")):
            continue
        is_meta = False
        cleaned.append(line)

    result = "\n".join(cleaned).strip()
    # Если фильтр всё вырезал, возвращаем последнюю непустую строку
    if not result:
        non_empty = [l.strip() for l in lines if l.strip()]
        result = non_empty[-1] if non_empty else text

    # Убираем случайные внешние кавычки
    return result.strip().strip('"').strip("'").strip()

async def get_best_model(session: aiohttp.ClientSession, api_key: str, headers: dict) -> list:
    """Запрашивает список доступных моделей у Google, исключая thinking-модели."""
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
                    name = m.get("name", "").replace("models/", "")
                    # Исключаем thinking-модели, которые печатают рассуждения вслух
                    if "thinking" in name.lower():
                        continue
                    if "generateContent" in m.get("supportedGenerationMethods", []):
                        if "flash" in name.lower() and name not in candidates:
                            candidates.append(name)
    except Exception as e:
        logger.warning(f"Ошибка получения списка моделей: {e}")

    # Надежные стандартные модели
    fallback_defaults = [
        "gemini-1.5-flash",
        "gemini-2.0-flash",
        "gemini-1.5-flash-8b",
        "gemini-1.5-pro"
    ]
    for d in fallback_defaults:
        if d not in candidates:
            candidates.append(d)

    return candidates

async def ask_ai(prompt: str) -> str:
    """Отправляет запрос к Google Gemini с передачей точной даты и гарантией чистого ответа."""
    global CACHED_MODEL
    raw_key = os.getenv("GEMINI_API_KEY", "")
    api_key = raw_key.strip().strip('"').strip("'")

    if not api_key:
        return "⚠️ Переменная GEMINI_API_KEY не настроена на сервере Render."

    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": api_key
    }

    now_dt = get_now()
    months_ru = [
        "января", "февраля", "марта", "апреля", "мая", "июня",
        "июля", "августа", "сентября", "октября", "ноября", "декабря"
    ]
    cur_date_str = f"{now_dt.day} {months_ru[now_dt.month - 1]} {now_dt.year} года, {now_dt.strftime('%H:%M')}"

    # Лаконичная инструкция без провоцирующих слов
    system_instruction = (
        f"Ты умный и полезный русскоязычный ассистент в Telegram. "
        f"Сегодняшняя дата: {cur_date_str}. "
        "Отвечай сразу готовым текстом на русском языке, кратко и вежливо."
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
                                raw_text = "\n".join(texts)
                                return clean_response(raw_text)
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
        return f"⚠️ Не удалось подключиться к Gemini: {last_error_text[:200]}"
