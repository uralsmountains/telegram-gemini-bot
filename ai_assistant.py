import os
import json
import logging
import aiohttp

logger = logging.getLogger(__name__)

CACHED_MODEL = None

async def get_best_model(session: aiohttp.ClientSession, api_key: str, headers: dict) -> list:
    """Динамически запрашивает список доступных моделей у Google для этого ключа."""
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

    # Стандартный список на случай, если list models не сработал
    fallback_defaults = [
        "gemini-1.5-flash",
        "gemini-1.5-pro",
        "gemini-2.0-flash",
        "gemini-2.0-flash-exp",
        "gemini-1.0-pro"
    ]
    for d in fallback_defaults:
        if d not in candidates:
            candidates.append(d)

    return candidates

async def ask_ai(prompt: str) -> str:
    """Отправляет запрос к Google Gemini API с автоопределением доступной модели."""
    global CACHED_MODEL
    raw_key = os.getenv("GEMINI_API_KEY", "")
    api_key = raw_key.strip().strip('"').strip("'")

    if not api_key:
        return "⚠️ Переменная GEMINI_API_KEY не найдена на сервере Render."

    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": api_key
    }

    payload = {
        "contents": [
            {
                "parts": [{"text": prompt}]
            }
        ],
        "systemInstruction": {
            "parts": [
                {
                    "text": "Ты полезный, дружелюбный и умный ИИ-помощник в Telegram. Отвечай кратко, понятно и по делу на русском языке."
                }
            ]
        }
    }

    last_error_text = ""

    async with aiohttp.ClientSession() as session:
        models_to_try = await get_best_model(session, api_key, headers)

        for model in models_to_try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
            try:
                # 1. Запрос с системной инструкцией
                async with session.post(url, headers=headers, json=payload, timeout=25) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        candidates = data.get("candidates", [])
                        if candidates:
                            parts = candidates[0].get("content", {}).get("parts", [])
                            texts = [p.get("text", "") for p in parts if "text" in p]
                            if texts:
                                CACHED_MODEL = model
                                return "\n".join(texts)
                    else:
                        err_body = await resp.text()
                        logger.warning(f"Модель {model} вернула {resp.status}: {err_body}")
                        last_error_text = err_body

                # 2. Фолбэк без systemInstruction (для более старых моделей)
                simple_payload = {"contents": [{"parts": [{"text": prompt}]}]}
                async with session.post(url, headers=headers, json=simple_payload, timeout=25) as resp2:
                    if resp2.status == 200:
                        data2 = await resp2.json()
                        candidates = data2.get("candidates", [])
                        if candidates:
                            parts = candidates[0].get("content", {}).get("parts", [])
                            texts = [p.get("text", "") for p in parts if "text" in p]
                            if texts:
                                CACHED_MODEL = model
                                return "\n".join(texts)
            except Exception as e:
                logger.warning(f"Ошибка запроса к {model}: {e}")
                last_error_text = str(e)

    # Если все модели вернули ошибку
    try:
        err_json = json.loads(last_error_text)
        msg = err_json.get("error", {}).get("message", last_error_text)
        return f"⚠️ Ошибка Gemini: {msg}"
    except Exception:
        return f"⚠️ Не удалось подключиться к Gemini: {last_error_text[:200]}"
