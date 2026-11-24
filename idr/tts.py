"""Narration with Kokoro (local, no API key). One clip per sentence, cached on disk."""
from __future__ import annotations

import hashlib
import json
import sys
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import soundfile as sf

from .env import MODEL, RELEASE, VOICES, cache_dir

SAMPLE_RATE = 24000


class VoiceUnavailable(RuntimeError):
    """The voice model is not on this machine and could not be downloaded."""


@dataclass
class Clip:
    """One spoken sentence. `words` holds (start, end, phonemes) for each spoken word, when the model reports it."""
    samples: np.ndarray
    duration: float
    words: list[tuple[float, float, int]] = field(default_factory=list)


def _fetch(name: str) -> Path:
    dest = cache_dir() / name
    if dest.exists():
        return dest
    print(f"[tts] downloading {name} (first run only)...", file=sys.stderr)
    part = dest.with_suffix(dest.suffix + ".part")
    try:
        urllib.request.urlretrieve(f"{RELEASE}/{name}", part)
    except OSError as problem:
        part.unlink(missing_ok=True)
        raise VoiceUnavailable(f"could not download {name}: {problem}") from None
    part.rename(dest)
    return dest


def _key(text: str, voice: str, speed: float, lang: str) -> str:
    return hashlib.sha256(f"timed|{MODEL}|{voice}|{speed}|{lang}|{text}".encode()).hexdigest()[:20]


def remembered(text: str, voice: str = "af_heart", speed: float = 1.0, lang: str = "en-us"):
    """How long a sentence took, and when each word fell, if it has been spoken before on this machine.
    Lets a check give real lengths for every sentence that has not changed since the last render."""
    key = _key(text, voice, speed, lang)
    wav, meta = cache_dir() / "clips" / f"{key}.wav", cache_dir() / "clips" / f"{key}.json"
    if not (wav.exists() and meta.exists()):
        return None
    try:
        return sf.info(str(wav)).duration, [tuple(w) for w in json.loads(meta.read_text())]
    except (RuntimeError, ValueError, OSError):
        return None


class Narrator:
    def __init__(self, voice: str = "af_heart", speed: float = 1.0, lang: str = "en-us"):
        self.voice, self.speed, self.lang = voice, speed, lang
        self._kokoro = None
        self.clips = cache_dir() / "clips"
        self.clips.mkdir(exist_ok=True)

    def _engine(self):
        if self._kokoro is None:
            from kokoro_onnx import Kokoro
            self._kokoro = Kokoro(str(_fetch(MODEL)), str(_fetch(VOICES)))
        return self._kokoro

    def say(self, text: str) -> Clip:
        """Speak one sentence: mono float32 samples at 24 kHz, with word timings when available."""
        key = _key(text, self.voice, self.speed, self.lang)
        wav, meta = self.clips / f"{key}.wav", self.clips / f"{key}.json"
        if wav.exists() and meta.exists():
            samples, _ = sf.read(wav, dtype="float32")
            words = [tuple(w) for w in json.loads(meta.read_text())]
        else:
            samples, sr, timings = self._engine().create_timed(text, voice=self.voice, speed=self.speed, lang=self.lang)
            assert sr == SAMPLE_RATE, sr
            samples, cut = _trim(np.asarray(samples, dtype=np.float32))
            words = _words(timings, cut, len(samples) / SAMPLE_RATE)
            sf.write(wav, samples, SAMPLE_RATE)
            meta.write_text(json.dumps(words))
        return Clip(samples, len(samples) / SAMPLE_RATE, words)


def _words(timings, cut: float, duration: float) -> list[tuple[float, float, int]]:
    """Group per-phoneme timings into words (split on spaces), shifted by what was trimmed off the front."""
    words, start, end, count = [], 0.0, 0.0, 0
    for timing in [*timings, None]:
        if timing is not None and timing.phoneme != " ":
            if not count:
                start = timing.start
            end, count = timing.end, count + 1
            continue
        if count:
            words.append((round(max(0.0, start - cut), 3), round(min(duration, end - cut), 3), count))
        count = 0
    return words


def _trim(samples: np.ndarray, floor: float = 0.004, pad: float = 0.04) -> tuple[np.ndarray, float]:
    """Cut leading/trailing silence so beats start on the first spoken sound. Returns (samples, seconds cut off the front)."""
    loud = np.flatnonzero(np.abs(samples) > floor)
    if loud.size == 0:
        return samples, 0.0
    keep = int(pad * SAMPLE_RATE)
    first = max(0, loud[0] - keep)
    return samples[first: loud[-1] + keep], first / SAMPLE_RATE
