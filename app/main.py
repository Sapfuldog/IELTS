"""Bot entry point: wires config, storage, DB and routers, then polls."""
from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import sys
from pathlib import Path

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
            BotCommand(command="reading", description="📖 Reading practice"),
            BotCommand(command="listening", description="🎧 Listening practice"),
            BotCommand(command="writing", description="✍️ Writing tasks"),
            BotCommand(command="speaking", description="🗣 Speaking practice"),
            BotCommand(command="vocabulary", description="🔤 Vocabulary flashcards"),
            BotCommand(command="test", description="📝 Full mock test with a band score"),
            BotCommand(command="progress", description="📊 Your progress"),
            BotCommand(command="help", description="How to use the bot"),
            BotCommand(command="cancel", description="Stop the current exercise"),
        ]
    )


class AlreadyRunning(RuntimeError):
    """Another instance holds the lock."""


def claim_single_instance(path: Path) -> Path:
    """Refuse to start when another instance is already polling.

    Two processes on one token both call getUpdates, and Telegram hands each
    update to whichever asks first — so the learner talks to one of them at
    random, quite possibly the one running older code. The symptom is "the bot
    is broken", not "there are two of it", which is why this is worth a guard
    rather than a note in the README.

    A stale file from a killed process is reclaimed: only a live PID counts.
    """
    if path.exists():
        try:
            pid = int(path.read_text().strip())
        except (ValueError, OSError):
            pid = None
        if pid and pid != os.getpid() and _is_running(pid):
            raise AlreadyRunning(
                f"another bot instance is already running (PID {pid}).\n"
                "   Stop it first — two instances on one token fight over "
                "updates, and which one answers is unpredictable."
            )

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(os.getpid()), encoding="utf-8")
    return path


def _is_running(pid: int) -> bool:
    """True if a process with this id exists. Errs towards 'yes'.

    Wrongly believing a dead process is alive costs a puzzled restart;
    wrongly believing a live one is dead brings back the bug this prevents.
    """
    if sys.platform == "win32":
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
            capture_output=True, text=True, check=False,
        )
        return str(pid) in result.stdout
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


async def main() -> None:
    config = load_config()

    lock = config.db_path.parent / "bot.pid"
    try:
        claim_single_instance(lock)
    except AlreadyRunning as exc:
        raise SystemExit(f"❌ {exc}") from None

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
        lock.unlink(missing_ok=True)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped.")
    # SystemExit is intentionally not caught: startup failures must surface
    # their message and a non-zero exit code.
