import os
import logging
import aiohttp

logger = logging.getLogger(__name__)

GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent"

async def ask_ai(prompt: str) -> str:
    """
    Отправляет запрос к Google Gemini 1.5 Flash с поддержкой поиска Google Search Grounding.
    """
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return "⚠️ Ключ ИИ (GEMINI_API_KEY) не настроен на сервере."

    url = f"{GEMINI_API_URL}?key={api_key}"

    # Пытаемся сделать запрос с Google Search для самых актуальных данных на сегодняшний день
    payload_with_search = {
        "contents": [
            {
                "role": "user",
                "parts": [{"text": prompt}]
            }
        ],
        "systemInstruction": {
            "parts": [
                {
                    "text": (
                        "Ты полезный, дружелюбный и современный русскоязычный ИИ-ассистент в Telegram. "
                        "Отвечай емко, по делу и дружелюбно. Используй Markdown для красивого оформления."
                    )
                }
            ]
        },
        "tools": [
            {"google_search": {}}
        ]
    }

    try:
        async with aiohttp.ClientSession() as session:
            # 1. Запрос с Google Search
            async with session.post(url, json=payload_with_search, timeout=30) as resp:
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
                    logger.warning(f"Ошибка Gemini с поиском (статус {resp.status}): {err_text}")

            # 2. Фолбэк: если с поиском не прошло, отправляем стандартный запрос
            payload_basic = {
                "contents": [
                    {
                        "role": "user",
                        "parts": [{"text": prompt}]
                    }
                ]
            }
            async with session.post(url, json=payload_basic, timeout=30) as resp2:
                if resp2.status == 200:
                    data = await resp2.json()
                    candidates = data.get("candidates", [])
                    if candidates:
                        parts = candidates[0].get("content", {}).get("parts", [])
                        texts = [p.get("text", "") for p in parts if "text" in p]
                        if texts:
                            return "\n".join(texts)
                else:
                    err2 = await resp2.text()
                    logger.error(f"Ошибка Gemini (статус {resp2.status}): {err2}")
                    return "⚠️ Не удалось получить ответ от ИИ. Попробуйте еще раз."

    except Exception as e:
        logger.error(f"Исключение при обращении к ИИ: {e}")
        return f"⚠️ Ошибка связи с ИИ: {e}"

    return "⚠️ ИИ не смог сгенерировать ответ."
