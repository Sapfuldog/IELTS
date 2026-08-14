"""Application configuration loaded from environment variables."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
CONTENT_DIR = BASE_DIR / "content"


@dataclass(frozen=True)
class Config:
    bot_token: str
    db_path: Path
    anthropic_api_key: str | None
    anthropic_model: str
    telegram_proxy: str | None

    @property
    def ai_enabled(self) -> bool:
        return bool(self.anthropic_api_key)


def load_config() -> Config:
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError(
            "BOT_TOKEN is not set. Copy .env.example to .env and add a token "
            "from @BotFather."
        )

    db_path = Path(os.getenv("DB_PATH", "data/ielts.db"))
    db_path.parent.mkdir(parents=True, exist_ok=True)

    return Config(
        bot_token=token,
        db_path=db_path,
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", "").strip() or None,
        anthropic_model=os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5").strip(),
        telegram_proxy=os.getenv("TELEGRAM_PROXY", "").strip() or None,
    )
