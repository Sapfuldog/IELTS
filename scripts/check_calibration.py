#!/usr/bin/env python3
"""Measure how well the configured model marks essays.

Generation is protected by a validator and a key audit. Marking has no such
backstop — a band is a number the learner acts on, and a miscalibrated one is
indistinguishable from a correct one. This is the substitute: a small set of
essays whose level is not in dispute, marked by whatever model is configured,
with the deviation reported.

Two things are measured, and the second matters more:

  Absolute deviation — how far each band is from the reference. Reference
  bands are indicative rather than official, so half a band either way is
  not alarming.

  Rank order — whether a weaker essay ever scores above a stronger one. This
  needs no agreement about the scale at all. A model that ranks the band 4
  essay above the band 8 one is unusable for marking regardless of how its
  numbers are calibrated, and this is the check to run after any model change.

Usage:
    python scripts/check_calibration.py
Exits 0 if the order is preserved and the mean deviation is within tolerance.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import CONTENT_DIR, load_config  # noqa: E402
from app.services.agent import TutorAgent  # noqa: E402

# Half a band is the width of one step on the scale; a mean drift larger than
# that means the numbers are describing something other than the scale.
TOLERANCE = 0.5


def load_samples() -> list[dict]:
    with (CONTENT_DIR / "calibration.json").open(encoding="utf-8") as fh:
        return json.load(fh)


async def main() -> int:
    config = load_config()
    agent = TutorAgent(config)
    if not agent.available:
        print("No API key configured — nothing to measure.")
        return 1

    samples = sorted(load_samples(), key=lambda s: s["reference_band"])
    print(f"model: {config.model}\n")

    results: list[tuple[dict, float | None]] = []
    for sample in samples:
        task = {"task": 2, "prompt": sample["prompt"]}
        marked = await agent.evaluate("writing", task, sample["essay"])
        band = marked.band if marked else None
        results.append((sample, band))

        reference = sample["reference_band"]
        if band is None:
            print(f"  {sample['id']}  reference {reference}  ->  FAILED to mark")
            continue
        drift = band - reference
        flag = "  " if abs(drift) <= TOLERANCE else " !"
        print(f"  {sample['id']}  reference {reference}  ->  {band}  ({drift:+.1f}){flag}")
        print(f"        {sample['note']}")

    marked = [(s, b) for s, b in results if b is not None]
    if len(marked) < 2:
        print("\nToo few essays were marked to judge anything.")
        return 1

    print()
    deviations = [abs(b - s["reference_band"]) for s, b in marked]
    mean = sum(deviations) / len(deviations)
    print(f"mean deviation: {mean:.2f} band (tolerance {TOLERANCE})")

    # Rank order: walk the essays weakest to strongest and check the marks
    # never go backwards. Ties are allowed — the model may see two as equal —
    # but an inversion is not.
    inversions = [
        (marked[i][0]["id"], marked[j][0]["id"])
        for i in range(len(marked))
        for j in range(i + 1, len(marked))
        if marked[j][1] < marked[i][1]
    ]
    if inversions:
        print("rank order: BROKEN")
        for weaker, stronger in inversions:
            print(f"  {weaker} scored above {stronger}, which is the wrong way round")
    else:
        print("rank order: preserved — no weaker essay outscored a stronger one")

    ok = not inversions and mean <= TOLERANCE
    print("\n" + ("Marking looks usable." if ok else "Marking is not trustworthy as it stands."))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
