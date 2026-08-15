#!/usr/bin/env python3
"""Check that AI feedback is actually wired up and reachable.

Answers, in order: is a key configured, is the model id valid, can this machine
reach api.anthropic.com, and does a real request come back. Each step prints
its own verdict, so a failure tells you which link in the chain is broken
instead of just "AI feedback unavailable".

Usage:  python scripts/check_ai.py
Exits 0 if a real request succeeded, 1 otherwise.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import load_config  # noqa: E402


_PREFIXES = {"anthropic": "sk-ant-", "openrouter": "sk-or-"}


def main() -> int:
    import asyncio

    from app.services.agent import TutorAgent

    config = load_config()
    provider = config.ai_provider

    print("1. Configuration")
    if provider is None:
        print("   No API key set — AI features are off and the bot falls back to")
        print("   the rule-based evaluator and the shipped exercise bank.")
        print("   Set OPENROUTER_API_KEY or ANTHROPIC_API_KEY in .env.")
        return 1

    key = (
        config.openrouter_api_key
        if provider == "openrouter"
        else config.anthropic_api_key
    )
    print(f"   provider: {provider}")
    print(f"   key:      {key[:11]}… ({len(key)} chars)")
    print(f"   model:    {config.model}")
    expected = _PREFIXES[provider]
    if not key.startswith(expected):
        print(f"   ⚠️  {provider} keys start with '{expected}' — this looks like a")
        print("      different credential pasted into the wrong variable.")

    print("\n2. Live structured-output request")
    schema = {
        "type": "object",
        "properties": {"reply": {"type": "string"}},
        "required": ["reply"],
        "additionalProperties": False,
    }
    agent = TutorAgent(config)
    try:
        payload = asyncio.run(
            agent._ask("Reply with the single word OK.", schema, max_tokens=64)
        )
    except Exception as exc:  # noqa: BLE001 — this script reports every failure
        print(f"   FAILED — {exc.__class__.__name__}: {exc}")
        return 1
    print(f"   OK — model returned {payload!r}")

    print("\n3. Generating a real exercise (the full agent loop)")
    exercise = asyncio.run(agent.generate("reading", topic="urban transport"))
    if exercise is None:
        print("   FAILED — nothing survived validation. See the log above.")
        return 1
    print(f"   OK — {exercise['title']!r}, {len(exercise['questions'])} questions")
    print("        (not saved; use the button in the bot to keep one)")

    print("\nAI features are working.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
