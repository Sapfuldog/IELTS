"""Aggregates all routers in registration order.

Order matters, and the two ends of the list are load-bearing:

* `common.router` (/start, /help, /cancel) goes FIRST. The section routers
  hold the user in an FSM state while an exercise is running, and those
  state handlers match any message — including a command. Registered later,
  /cancel would be graded as a quiz answer instead of cancelling.
* `common.fallback_router` goes LAST, since it matches everything.
"""
from aiogram import Router

from . import common, progress, quiz, speaking, vocabulary, writing


def build_router() -> Router:
    root = Router(name="root")
    root.include_router(common.router)  # global commands — must stay first
    root.include_router(quiz.router)
    root.include_router(writing.router)
    root.include_router(speaking.router)
    root.include_router(vocabulary.router)
    root.include_router(progress.router)
    root.include_router(common.fallback_router)  # catch-all — must stay last
    return root
