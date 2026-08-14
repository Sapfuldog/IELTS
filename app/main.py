"""Bot entry point: wires config, storage, DB and routers, then polls."""
from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramNetworkError, TelegramUnauthorizedError
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


def _build_session(config) -> AiohttpSession | None:
    """Custom session only when a proxy is configured."""
    if not config.telegram_proxy:
        return None
    try:
        return AiohttpSession(proxy=config.telegram_proxy)
    except RuntimeError as exc:
        # aiogram needs aiohttp-socks for proxied requests.
        raise SystemExit(
            f"❌ TELEGRAM_PROXY is set but proxy support is unavailable: {exc}\n"
            "   Install it with:  pip install aiohttp-socks"
        ) from None


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

    session = _build_session(config)
    bot = Bot(
        token=config.bot_token,
        session=session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())

    # Injected into any handler that declares these parameter names.
    dp["db"] = db
    dp["config"] = config

    dp.include_router(build_router())

    try:
        me = await bot.get_me()
    except TelegramUnauthorizedError:
        await bot.session.close()
        raise SystemExit(
            "❌ Telegram rejected the token.\n"
            "   Check BOT_TOKEN in .env, or issue a new one with /newbot in @BotFather."
        ) from None
    except TelegramNetworkError as exc:
        await bot.session.close()
        raise SystemExit(
            f"❌ Could not reach api.telegram.org ({exc.__class__.__name__}).\n"
            "   The code is fine — this is a network problem. Check that:\n"
            "   • this machine has internet access and Telegram is not blocked;\n"
            "   • if you are behind a proxy, set TELEGRAM_PROXY in .env,\n"
            "     e.g. TELEGRAM_PROXY=http://user:pass@host:port"
        ) from None

    logger.info(
        "Started as @%s (id=%s) — AI feedback: %s",
        me.username,
        me.id,
        "on" if config.ai_enabled else "off",
    )

    await _set_commands(bot)
    await bot.delete_webhook(drop_pending_updates=True)
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped.")
    # SystemExit is intentionally not caught: startup failures must surface
    # their message and a non-zero exit code.
