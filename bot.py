import os
import sys
import logging
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from dotenv import load_dotenv
from telegram import Update
from telegram.constants import ParseMode, ChatAction
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from google import genai
from google.genai import types

# Ensure stdout flushes immediately
sys.stdout.reconfigure(line_buffering=True)

# Load environment variables
load_dotenv(override=True)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_PROXY = os.getenv("TELEGRAM_PROXY", "").strip()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()

# Setup logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Initialize Gemini Client with Proxy
client = None
if GEMINI_API_KEY:
    try:
        http_opts = types.HttpOptions(client_args={"proxy": TELEGRAM_PROXY}) if TELEGRAM_PROXY else None
        client = genai.Client(api_key=GEMINI_API_KEY, http_options=http_opts)
        logger.info("Gemini client successfully initialized with proxy.")
    except Exception as e:
        logger.error(f"Failed to initialize Gemini client: {e}")

# In-memory chat history: user_id -> list of {'role': ..., 'parts': [...]}
user_histories = {}
MODELS = ["gemini-3.8-flash", "gemini-3.5-flash-lite"]


def split_message(text: str, max_length: int = 4000):
    """Splits text into chunks fitting Telegram message limit."""
    chunks = []
    while len(text) > max_length:
        split_at = text.rfind("\n", 0, max_length)
        if split_at == -1:
            split_at = max_length
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip("\n")
    if text:
        chunks.append(text)
    return chunks


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles /start command."""
    user = update.effective_user
    greeting = (
        f"👋 Привет, {user.first_name}!\n\n"
        f"Я твой личный AI-ассистент в Telegram на базе Gemini 3.8 Flash.\n\n"
        f"🔒 *Безопасность:*\n"
        f"Я нахожусь только в этом личном диалоге. Я не имею доступа к твоим контактам, "
        f"другим чатам или черновикам.\n\n"
        f"📌 *Команды:*\n"
        f"• Просто пиши любой вопрос или задачу.\n"
        f"• /reset — начать новый диалог (очистить историю).\n"
        f"• /status — статус подключения и модели."
    )
    await update.message.reply_text(greeting, parse_mode=ParseMode.MARKDOWN)


async def reset_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Clears conversation context."""
    user_id = update.effective_user.id
    if user_id in user_histories:
        del user_histories[user_id]
    await update.message.reply_text("🧹 Память диалога очищена. О чём поговорим?")


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Reports bot status."""
    has_key = "✅ Активен" if GEMINI_API_KEY else "❌ Не указан"
    status_text = (
        f"⚙️ *Статус системы:*\n"
        f"• Бот: ✅ Онлайн (@{context.bot.username})\n"
        f"• Gemini AI: {has_key}\n"
        f"• Модель: `{MODELS[0]}`\n"
        f"• Ваш ID: `{update.effective_user.id}`"
    )
    await update.message.reply_text(status_text, parse_mode=ParseMode.MARKDOWN)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles incoming user messages."""
    user_id = update.effective_user.id
    text = update.message.text

    if not text:
        return

    await update.message.chat.send_action(action=ChatAction.TYPING)

    global client
    if not client:
        load_dotenv(override=True)
        current_key = os.getenv("GEMINI_API_KEY", "").strip()
        if current_key:
            try:
                http_opts = types.HttpOptions(client_args={"proxy": TELEGRAM_PROXY}) if TELEGRAM_PROXY else None
                client = genai.Client(api_key=current_key, http_options=http_opts)
            except Exception as err:
                logger.error(f"Error initializing Gemini: {err}")

    if not client:
        await update.message.reply_text("⚠️ Ошибка: Gemini API ключ не загружен.")
        return

    # Maintain history
    if user_id not in user_histories:
        user_histories[user_id] = []

    history = user_histories[user_id]
    history.append(types.Content(role="user", parts=[types.Part.from_text(text=text)]))

    answer = None
    last_err = None

    for model_name in MODELS:
        try:
            res = client.models.generate_content(
                model=model_name,
                contents=history
            )
            if res and res.text:
                answer = res.text
                break
        except Exception as e:
            last_err = e
            logger.warning(f"Model {model_name} failed: {e}, trying next...")
            continue

    if not answer:
        logger.error(f"All models failed: {last_err}")
        await update.message.reply_text(f"⚠️ Не удалось получить ответ: {last_err}")
        # remove failed user message from history
        if history:
            history.pop()
        return

    # Add model answer to history
    history.append(types.Content(role="model", parts=[types.Part.from_text(text=answer)]))

    # Keep conversation history bounded to last 20 messages
    if len(history) > 20:
        user_histories[user_id] = history[-20:]

    for chunk in split_message(answer):
        try:
            await update.message.reply_text(chunk, parse_mode=ParseMode.MARKDOWN)
        except Exception:
            await update.message.reply_text(chunk)


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Bot is alive!")

    def log_message(self, format, *args):
        pass


def run_health_server():
    port_str = os.getenv("PORT", "").strip()
    if port_str and port_str.isdigit():
        port = int(port_str)
        server = HTTPServer(("0.0.0.0", port), HealthHandler)
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        logger.info(f"Health server started on port {port}")


def main():
    run_health_server()
    if not TELEGRAM_BOT_TOKEN:
        print("Ошибка: TELEGRAM_BOT_TOKEN не указан в файле .env")
        return

    print("Запуск бота Telegram с поддержкой Gemini...")
    builder = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN)

    if TELEGRAM_PROXY:
        print(f"Используем прокси: {TELEGRAM_PROXY}")
        builder = builder.proxy(TELEGRAM_PROXY).get_updates_proxy(TELEGRAM_PROXY)

    application = builder.build()

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("reset", reset_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("Бот готов к общению!")
    application.run_polling()


if __name__ == "__main__":
    main()
