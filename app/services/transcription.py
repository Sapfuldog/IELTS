"""Turn a voice answer into text, locally.

Speaking was typed until now, which trained composing sentences rather than
speaking them. Whisper runs on this machine: the recording never leaves it,
which matters because these are learners' voices and there is no reason to
send them anywhere.

What comes back is not only words. Segment timings give pace and pauses —
measurements a typed answer cannot produce and an examiner explicitly listens
for. They are reported as observations, not as a band: how long someone paused
is a fact, what it says about their fluency is a judgement, and the two should
not be presented as the same thing.

The model is optional. Without it the section falls back to typed answers, as
it worked before.
"""
from __future__ import annotations

import io
import logging
import os
import sys
from pathlib import Path

import numpy as np
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

MODEL_SIZE = "small"

# A pause this long reads as hesitation rather than as phrasing. Shorter gaps
# are ordinary sentence rhythm and counting them would flag fluent speakers.
PAUSE_SECONDS = 1.5

_model = None
_unavailable = False


@dataclass
class Transcript:
    """What was said, and measurements of how it was said."""

    text: str
    duration: float = 0.0
    words: int = 0
    long_pauses: int = 0
    longest_pause: float = 0.0
    confidence: float = 0.0  # mean of the model's own per-segment score
    segments: list[tuple[float, float]] = field(default_factory=list)

    @property
    def words_per_minute(self) -> float:
        return self.words / (self.duration / 60) if self.duration else 0.0

    def observations(self) -> list[str]:
        """Plain statements of fact about the delivery, with no verdict attached."""
        notes = [
            f"spoke for {self.duration:.0f} seconds, {self.words} words "
            f"(about {self.words_per_minute:.0f} words per minute)"
        ]
        if self.long_pauses:
            notes.append(
                f"{self.long_pauses} pause(s) over {PAUSE_SECONDS:g}s, "
                f"longest {self.longest_pause:.1f}s"
            )
        else:
            notes.append("no long pauses")
        return notes

    def delivery_evidence(self) -> str:
        """What the audio shows about delivery, for the marker to weigh.

        This is the only evidence about pronunciation the bot has, and it is
        worth being exact about what it is. Whisper's confidence measures how
        readily the speech was recognised — intelligibility, which is what the
        Pronunciation descriptors turn on at the lower bands. It says nothing
        about individual sounds or intonation, so the marker is told that too
        rather than being left to assume it has more than it does.
        """
        clarity = (
            "easily recognised throughout" if self.confidence > -0.35
            else "mostly clear, some words hard to make out" if self.confidence > -0.6
            else "frequently hard to make out"
        )
        pace = (
            "very slow" if self.words_per_minute < 90
            else "measured" if self.words_per_minute < 120
            else "natural" if self.words_per_minute < 170
            else "fast"
        )
        return (
            f"Speech evidence from the recording (not a transcript of sounds): "
            f"the recogniser found the speech {clarity}; pace was {pace} at "
            f"{self.words_per_minute:.0f} words per minute over "
            f"{self.duration:.0f} seconds; {self.long_pauses} hesitation "
            f"pause(s) longer than {PAUSE_SECONDS:g}s"
            + (f", the longest {self.longest_pause:.1f}s" if self.long_pauses else "")
            + "."
        )

    @property
    def uncertain(self) -> bool:
        """Whether the model itself found the audio hard to make out.

        Accented speech is exactly what this bot exists to help with and
        exactly what transcription gets wrong, so a low score is worth showing
        the learner rather than quietly marking them on a bad transcript.
        """
        return self.confidence < -0.6


def available() -> bool:
    return not _unavailable


def _add_cuda_libraries() -> None:
    """Point Windows at the CUDA DLLs shipped by the nvidia-* wheels.

    They install under site-packages, which is not on the DLL search path, so
    CTranslate2 loads the model happily and then fails on the first inference
    with "cublas64_12.dll is not found". Harmless when the packages are
    absent — the loader falls back to the CPU.
    """
    if not hasattr(os, "add_dll_directory"):
        return  # not Windows
    root = Path(sys.prefix) / "Lib" / "site-packages" / "nvidia"
    for folder in root.glob("*/bin"):
        try:
            os.add_dll_directory(str(folder))
        except OSError:
            pass


def _load():
    global _model, _unavailable
    if _model is not None or _unavailable:
        return _model
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        logger.info("faster-whisper is not installed — Speaking stays text-only.")
        _unavailable = True
        return None

    _add_cuda_libraries()
    for device, compute in (("cuda", "float16"), ("cpu", "int8")):
        try:
            model = WhisperModel(MODEL_SIZE, device=device, compute_type=compute)
            # Loading succeeds on a GPU whose libraries are missing; only a
            # real inference proves the device works, so run a silent one.
            model.transcribe(np.zeros(16000, dtype=np.float32))
            _model = model
            logger.info("Whisper %s loaded on %s.", MODEL_SIZE, device)
            return _model
        except Exception as exc:
            logger.info("Whisper cannot use %s (%s); trying the next option.",
                        device, exc.__class__.__name__)
    logger.warning("Whisper could not be loaded — Speaking stays text-only.")
    _unavailable = True
    return None


def _measure(segments: list) -> Transcript:
    texts, spans, scores = [], [], []
    for segment in segments:
        texts.append(segment.text.strip())
        spans.append((segment.start, segment.end))
        scores.append(getattr(segment, "avg_logprob", 0.0))

    text = " ".join(t for t in texts if t)
    gaps = [
        spans[i + 1][0] - spans[i][1]
        for i in range(len(spans) - 1)
        if spans[i + 1][0] - spans[i][1] > 0
    ]
    long_gaps = [g for g in gaps if g >= PAUSE_SECONDS]
    return Transcript(
        text=text,
        duration=spans[-1][1] if spans else 0.0,
        words=len(text.split()),
        long_pauses=len(long_gaps),
        longest_pause=max(gaps) if gaps else 0.0,
        confidence=sum(scores) / len(scores) if scores else 0.0,
        segments=spans,
    )


def transcribe(audio: bytes) -> Transcript | None:
    """Transcribe a voice message. None when the model is unavailable or fails.

    Telegram sends OGG/OPUS; faster-whisper decodes it directly, so no
    external ffmpeg is needed.
    """
    model = _load()
    if model is None:
        return None
    try:
        segments, _info = model.transcribe(
            io.BytesIO(audio),
            language="en",
            # The learner is being assessed on English, so a mistaken guess at
            # another language would produce nonsense rather than an accent.
            vad_filter=True,
        )
        return _measure(list(segments))
    except Exception:
        logger.warning("Transcription failed.", exc_info=True)
        return None
