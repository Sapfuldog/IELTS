"""Draw a labelling diagram for the Listening and Reading sections.

Real papers show a process, a cycle or a plan and ask the candidate to label
parts of it. That is a reading-an-image skill, and describing the picture in
words would train something else — so the bot draws one.

Only flow diagrams are supported: an ordered chain of stages, some of which
are blanks the learner fills in. That single shape covers the most common
version of the task (water treatment, manufacturing, recycling) and needs no
layout engine — stages wrap across rows, arrows follow the reading order.

Kept free of aiogram so the layout can be tested without a bot, and returning
bytes rather than writing files so nothing has to be cleaned up.
"""
from __future__ import annotations

import io
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

BOX_WIDTH = 190
BOX_HEIGHT = 90
GAP_X = 60
GAP_Y = 70
MARGIN = 30
PER_ROW = 3

BACKGROUND = "white"
LINE = "#333333"
BLANK_FILL = "#fff6d5"   # a blank has to look obviously unfilled
BOX_FILL = "#eef3f8"


@dataclass(frozen=True)
class Placed:
    """One stage with the box it occupies."""

    label: str
    is_blank: bool
    left: int
    top: int

    @property
    def centre(self) -> tuple[int, int]:
        return self.left + BOX_WIDTH // 2, self.top + BOX_HEIGHT // 2


def is_blank(label: str) -> bool:
    """A stage written as '___1___' or '__2__' is for the learner to fill."""
    return label.strip().strip("_").isdigit() and "_" in label


def layout(steps: list[str]) -> tuple[list[Placed], tuple[int, int]]:
    """Place each stage, returning the boxes and the canvas size.

    Stages run left to right and wrap after PER_ROW, which is what keeps a
    ten-stage process readable on a phone rather than a strip too wide to see.
    """
    placed: list[Placed] = []
    for index, label in enumerate(steps):
        row, column = divmod(index, PER_ROW)
        placed.append(
            Placed(
                label=label,
                is_blank=is_blank(label),
                left=MARGIN + column * (BOX_WIDTH + GAP_X),
                top=MARGIN + row * (BOX_HEIGHT + GAP_Y),
            )
        )

    columns = min(len(steps), PER_ROW) or 1
    rows = (len(steps) + PER_ROW - 1) // PER_ROW or 1
    width = MARGIN * 2 + columns * BOX_WIDTH + (columns - 1) * GAP_X
    height = MARGIN * 2 + rows * BOX_HEIGHT + (rows - 1) * GAP_Y
    return placed, (width, height)


def _wrap(text: str, limit: int = 18) -> list[str]:
    lines: list[str] = []
    current = ""
    for word in text.split():
        candidate = f"{current} {word}".strip()
        if len(candidate) <= limit:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines[:3]


def render(title: str, steps: list[str]) -> bytes | None:
    """Draw the diagram as a PNG. None when Pillow is unavailable.

    Callers fall back to sending the stages as text: a missing picture must
    cost the diagram, not the whole exercise.
    """
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        logger.warning("Pillow is not installed — diagrams will be sent as text.")
        return None

    placed, (width, height) = layout(steps)
    header = 46 if title else 0
    image = Image.new("RGB", (width, height + header), BACKGROUND)
    draw = ImageDraw.Draw(image)

    if title:
        draw.text((MARGIN, 16), title, fill=LINE)

    for index, box in enumerate(placed):
        top = box.top + header
        draw.rectangle(
            [box.left, top, box.left + BOX_WIDTH, top + BOX_HEIGHT],
            fill=BLANK_FILL if box.is_blank else BOX_FILL,
            outline=LINE,
            width=2,
        )
        lines = _wrap(box.label)
        for line_no, line in enumerate(lines):
            draw.text(
                (box.left + 12, top + BOX_HEIGHT // 2 - 6 * len(lines) + line_no * 14),
                line,
                fill=LINE,
            )

        # Arrow to the next stage, following the reading order.
        if index + 1 < len(placed):
            nxt = placed[index + 1]
            if nxt.top == box.top:
                y = top + BOX_HEIGHT // 2
                draw.line([box.left + BOX_WIDTH, y, nxt.left, y], fill=LINE, width=2)
                draw.polygon(
                    [(nxt.left, y), (nxt.left - 10, y - 5), (nxt.left - 10, y + 5)],
                    fill=LINE,
                )
            else:
                # Wrapping to the next row: drop from this box, run back, rise.
                x = box.left + BOX_WIDTH // 2
                bottom = top + BOX_HEIGHT
                mid = bottom + GAP_Y // 2
                target = nxt.left + BOX_WIDTH // 2
                draw.line([x, bottom, x, mid], fill=LINE, width=2)
                draw.line([x, mid, target, mid], fill=LINE, width=2)
                draw.line([target, mid, target, nxt.top + header], fill=LINE, width=2)
                draw.polygon(
                    [
                        (target, nxt.top + header),
                        (target - 5, nxt.top + header - 10),
                        (target + 5, nxt.top + header - 10),
                    ],
                    fill=LINE,
                )

    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()
