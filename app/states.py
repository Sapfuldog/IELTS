"""Finite-state-machine states used across the bot."""
from aiogram.fsm.state import State, StatesGroup


class Quiz(StatesGroup):
    """Shared by Reading and Listening (passage/audio + questions)."""
    answering = State()


class Writing(StatesGroup):
    awaiting_essay = State()


class Speaking(StatesGroup):
    answering = State()


class Vocab(StatesGroup):
    reviewing = State()
