"""Sound effects. All of them are synthesized here, so the pack carries no third-party audio.

Run `python -m idr.sfx` to regenerate the wav files in idr/assets/sfx/.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import numpy as np
import soundfile as sf

RATE = 48000
DIR = Path(__file__).parent / "assets" / "sfx"


def _t(seconds: float) -> np.ndarray:
    return np.arange(int(seconds * RATE)) / RATE


def _norm(x: np.ndarray, peak: float = 0.8) -> np.ndarray:
    return (x / (np.abs(x).max() or 1.0) * peak).astype(np.float32)


def _fade(x: np.ndarray, ms_in: float = 2.0, ms_out: float = 8.0) -> np.ndarray:
    a, b = int(ms_in * RATE / 1000), int(ms_out * RATE / 1000)
    x = x.copy()
    x[:a] *= np.linspace(0, 1, a)
    x[-b:] *= np.linspace(1, 0, b)
    return x


def whoosh() -> np.ndarray:
    """Scene change: air moving past. Noise through a band-pass that sweeps up then down."""
    t = _t(0.42)
    noise = np.random.default_rng(7).standard_normal(t.size)
    pos = t / t[-1]
    cutoff = 500 + 3200 * np.sin(np.pi * pos) ** 1.5   # Hz
    low = band = 0.0
    out = np.empty_like(t)
    q = 0.9
    for i in range(t.size):                              # state-variable filter
        f = 2 * np.sin(np.pi * cutoff[i] / RATE)
        low += f * band
        high = noise[i] - low - q * band
        band += f * high
        out[i] = band
    env = np.sin(np.pi * pos) ** 2 * (0.55 + 0.45 * pos)
    return _norm(_fade(out * env, 5, 30))


def tick() -> np.ndarray:
    """Highlight lands on a line: a short, dry click."""
    t = _t(0.06)
    body = np.sin(2 * np.pi * 1900 * t) + 0.4 * np.sin(2 * np.pi * 3800 * t)
    click = np.random.default_rng(3).standard_normal(t.size) * np.exp(-t / 0.0015) * 0.5
    return _norm(_fade((body * np.exp(-t / 0.009)) + click, 0.5, 5), 0.7)


def pop() -> np.ndarray:
    """Something appears: a soft, round blip that drops in pitch."""
    t = _t(0.16)
    freq = 260 + 300 * np.exp(-t / 0.03)
    phase = 2 * np.pi * np.cumsum(freq) / RATE
    env = (1 - np.exp(-t / 0.002)) * np.exp(-t / 0.04)
    return _norm(_fade(np.sin(phase) * env, 1, 15))


def chime() -> np.ndarray:
    """Chapter title: two soft bell partials a fifth apart."""
    t = _t(1.2)
    x = (np.sin(2 * np.pi * 784 * t) * np.exp(-t / 0.35)
         + 0.6 * np.sin(2 * np.pi * 1175 * t) * np.exp(-t / 0.28)
         + 0.2 * np.sin(2 * np.pi * 2350 * t) * np.exp(-t / 0.12))
    return _norm(_fade(x * (1 - np.exp(-t / 0.004)), 2, 120), 0.75)


EFFECTS = {"whoosh": whoosh, "tick": tick, "pop": pop, "chime": chime}

# How loud each effect sits under the narration (linear gain on the 0.8-peak file).
GAIN = {"whoosh": 0.16, "tick": 0.22, "pop": 0.28, "chime": 0.22}


@lru_cache(maxsize=None)
def load(name: str) -> np.ndarray:
    samples, rate = sf.read(DIR / f"{name}.wav", dtype="float32")
    assert rate == RATE, rate
    return samples


def main() -> None:
    DIR.mkdir(parents=True, exist_ok=True)
    for name, make in EFFECTS.items():
        samples = make()
        sf.write(DIR / f"{name}.wav", samples, RATE, subtype="PCM_16")
        print(f"{name}: {samples.size / RATE:.2f}s, peak {np.abs(samples).max():.2f}")


if __name__ == "__main__":
    main()
