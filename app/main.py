"""Bot entry point: wires config, storage, DB and routers, then polls."""
from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand

from app.config import load_config
from app.db import Database
from app.handlers import build_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger("ielts-bot")


async def _set_commands(bot: Bot) -> None:
    await bot.set_my_commands(
        [
            BotCommand(command="start", description="Start / show the menu"),
            BotCommand(command="help", description="How to use the bot"),
            BotCommand(command="cancel", description="Stop the current exercise"),
        ]
    )


async def main() -> None:
    config = load_config()

    db = Database(config.db_path)
    await db.init()

    bot = Bot(
        token=config.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())

    # Injected into any handler that declares these parameter names.
    dp["db"] = db
    dp["config"] = config

    dp.include_router(build_router())

    await _set_commands(bot)
    logger.info("IELTS bot started (AI feedback: %s)", "on" if config.ai_enabled else "off")

    await bot.delete_webhook(drop_pending_updates=True)
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped.")
