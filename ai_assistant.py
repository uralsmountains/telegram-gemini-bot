import os
import json
import logging
import aiohttp

logger = logging.getLogger(__name__)

async def ask_ai(prompt: str) -> str:
    """
    Отправляет запрос к Google Gemini API (поддержка gemini-1.5-flash и gemini-2.0-flash).
    """
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return "⚠️ Ключ ИИ (GEMINI_API_KEY) не настроен на сервере Render."

    api_key = api_key.strip()
    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": api_key
    }

    # Пробуем актуальные модели: 1.5-flash, затем 2.0-flash
    models = ["gemini-1.5-flash", "gemini-2.0-flash", "gemini-1.5-flash-latest"]
    last_error = ""

    async with aiohttp.ClientSession() as session:
        for model in models:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"

            # 1. Попытка с поиском Google Search для самых свежих актуальных данных
            payload_search = {
                "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "tools": [{"google_search": {}}]
            }

            try:
                async with session.post(url, headers=headers, json=payload_search, timeout=25) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        candidates = data.get("candidates", [])
                        if candidates:
                            parts = candidates[0].get("content", {}).get("parts", [])
                            texts = [p.get("text", "") for p in parts if "text" in p]
                            if texts:
                                return "\n".join(texts)
                    else:
                        err_text = await resp.text()
                        logger.warning(f"Gemini {model} с поиском вернул {resp.status}: {err_text}")
                        last_error = f"{resp.status}: {err_text}"
            except Exception as e:
                logger.warning(f"Ошибка запроса с поиском для {model}: {e}")
                last_error = str(e)

            # 2. Фолбэк: обычный запрос к этой же модели (без инструментов)
            payload_simple = {
                "contents": [{"parts": [{"text": prompt}]}]
            }

            try:
                async with session.post(url, headers=headers, json=payload_simple, timeout=25) as resp2:
                    if resp2.status == 200:
                        data2 = await resp2.json()
                        candidates = data2.get("candidates", [])
                        if candidates:
                            parts = candidates[0].get("content", {}).get("parts", [])
                            texts = [p.get("text", "") for p in parts if "text" in p]
                            if texts:
                                return "\n".join(texts)
                    else:
                        err2 = await resp2.text()
                        logger.warning(f"Gemini {model} без поиска вернул {resp2.status}: {err2}")
                        last_error = f"{resp2.status}: {err2}"
            except Exception as e:
                logger.warning(f"Ошибка обычного запроса для {model}: {e}")
                last_error = str(e)

    # Если ни одна модель не ответила, выводим понятное объяснение ошибки
    try:
        err_json = json.loads(last_error.split(": ", 1)[-1])
        msg = err_json.get("error", {}).get("message", last_error)
        return f"⚠️ Ошибка от Google Gemini: {msg}"
    except Exception:
        return f"⚠️ Ошибка Gemini: {last_error[:250]}"
