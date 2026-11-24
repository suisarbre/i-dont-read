"""Narration with Kokoro (local, no API key). One clip per sentence, cached on disk."""
from __future__ import annotations

import hashlib
import sys
import urllib.request
from pathlib import Path

import numpy as np
import soundfile as sf

from .env import MODEL, RELEASE, VOICES, cache_dir

SAMPLE_RATE = 24000


class VoiceUnavailable(RuntimeError):
    """The voice model is not on this machine and could not be downloaded."""


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

    def say(self, text: str) -> tuple[np.ndarray, float]:
        """Return (mono float32 samples at 24 kHz, duration in seconds) for one sentence."""
        key = hashlib.sha256(f"{MODEL}|{self.voice}|{self.speed}|{self.lang}|{text}".encode()).hexdigest()[:20]
        path = self.clips / f"{key}.wav"
        if path.exists():
            samples, _ = sf.read(path, dtype="float32")
        else:
            samples, sr = self._engine().create(text, voice=self.voice, speed=self.speed, lang=self.lang)
            assert sr == SAMPLE_RATE, sr
            samples = _trim(np.asarray(samples, dtype=np.float32))
            sf.write(path, samples, SAMPLE_RATE)
        return samples, len(samples) / SAMPLE_RATE


def _trim(samples: np.ndarray, floor: float = 0.004, pad: float = 0.04) -> np.ndarray:
    """Cut leading/trailing silence so beats start on the first spoken sound."""
    loud = np.flatnonzero(np.abs(samples) > floor)
    if loud.size == 0:
        return samples
    keep = int(pad * SAMPLE_RATE)
    return samples[max(0, loud[0] - keep): loud[-1] + keep]
