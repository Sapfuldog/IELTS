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
    openrouter_api_key: str | None
    openrouter_model: str
    telegram_proxy: str | None

    @property
    def ai_provider(self) -> str | None:
        """Which backend the agent should use, or None when it has no key.

        OpenRouter wins when both are configured: setting it is the more
        deliberate act, since the bot works with Anthropic out of the box.
        """
        if self.openrouter_api_key:
            return "openrouter"
        if self.anthropic_api_key:
            return "anthropic"
        return None

    @property
    def ai_enabled(self) -> bool:
        return self.ai_provider is not None

    @property
    def model(self) -> str:
        return (
            self.openrouter_model
            if self.ai_provider == "openrouter"
            else self.anthropic_model
        )


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
        anthropic_model=os.getenv("ANTHROPIC_MODEL", "claude-opus-5").strip(),
        openrouter_api_key=os.getenv("OPENROUTER_API_KEY", "").strip() or None,
        openrouter_model=os.getenv(
            "OPENROUTER_MODEL", "nvidia/nemotron-3-super-120b-a12b:free"
        ).strip(),
        telegram_proxy=os.getenv("TELEGRAM_PROXY", "").strip() or None,
    )
