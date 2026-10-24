import asyncio
import logging
import os
import sys
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

import database
from handlers import router
from scheduler import setup_scheduler

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - [%(levelname)s] - %(name)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

async def main():
    token = os.getenv("BOT_TOKEN")
    if not token or token == "YOUR_TELEGRAM_BOT_TOKEN_HERE":
        logger.error(
            "\n"
            "==========================================================\n"
            "ОШИБКА: Токен бота не найден!\n"
            "1. Откройте файл .env в папке reminder_bot\n"
            "2. Вставьте ваш токен от @BotFather в строку BOT_TOKEN=...\n"
            "=========================================================="
        )
        return

    # Инициализация базы данных
    await database.init_db()
    logger.info("База данных успешно инициализирована.")

    # Инициализация бота и диспетчера
    bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.include_router(router)

    # Инициализация планировщика напоминаний
    scheduler = setup_scheduler(bot)
    scheduler.start()
    logger.info("Планировщик фоновых напоминаний запущен.")

    # Опциональный веб-сервер для облачных платформ (Render, Amvera, Koyeb), если задан PORT
    port_str = os.getenv("PORT")
    web_runner = None
    if port_str:
        try:
            from aiohttp import web
            port = int(port_str)
            app = web.Application()
            async def handle_ping(request):
                return web.Response(text="Bot is online and running 24/7!")
            app.router.add_get("/", handle_ping)
            app.router.add_get("/health", handle_ping)
            web_runner = web.AppRunner(app)
            await web_runner.setup()
            site = web.TCPSite(web_runner, "0.0.0.0", port)
            await site.start()
            logger.info(f"Healthcheck веб-сервер запущен на порту {port}")
        except Exception as e:
            logger.warning(f"Не удалось запустить healthcheck веб-сервер: {e}")

    # Удаление вебхука перед запуском поллинга
    await bot.delete_webhook(drop_pending_updates=True)
    logger.info("Бот запущен и готов к приему сообщений!")

    try:
        await dp.start_polling(bot)
    finally:
        scheduler.shutdown()
        if web_runner:
            await web_runner.cleanup()
        await bot.session.close()
        logger.info("Бот остановлен.")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Выход из программы.")
