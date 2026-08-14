"""Aggregates all routers in registration order.

Order matters: section routers come first so their specific filters win,
and `common` (with the catch-all fallback) is registered last.
"""
from aiogram import Router

from . import common, progress, quiz, speaking, vocabulary, writing


def build_router() -> Router:
    root = Router(name="root")
    root.include_router(quiz.router)
    root.include_router(writing.router)
    root.include_router(speaking.router)
    root.include_router(vocabulary.router)
    root.include_router(progress.router)
    root.include_router(common.router)  # must be last (has the fallback)
    return root
