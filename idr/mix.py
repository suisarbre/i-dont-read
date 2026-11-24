"""Build the soundtrack (narration + sound effects) and attach it to the picture."""
from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np
import soundfile as sf

from . import sfx
from .plan import Scene
from .tts import SAMPLE_RATE as VOICE_RATE


def _place(track: np.ndarray, at: float, samples: np.ndarray, rate: int, gain: float = 1.0) -> None:
    i = int(round(at * rate))
    n = min(len(samples), len(track) - i)
    if n > 0:
        track[i:i + n] += samples[:n] * gain


def soundtrack(scenes: list[Scene], workdir: Path) -> tuple[Path, Path]:
    """Write the narration track and the effects track, both as long as the video."""
    total = sum(s.duration for s in scenes)
    voice = np.zeros(int(round(total * VOICE_RATE)), dtype=np.float32)
    effects = np.zeros(int(round(total * sfx.RATE)), dtype=np.float32)
    start = 0.0
    for scene in scenes:
        for at, samples in scene.narration:
            _place(voice, start + at, samples, VOICE_RATE)
        for at, name in scene.sfx:
            _place(effects, start + at, sfx.load(name), sfx.RATE, sfx.GAIN[name])
        start += scene.duration
    peak = float(np.abs(voice).max())
    if peak > 0:
        voice *= 0.89 / peak                               # same narration level in every video
    voice_path, fx_path = workdir / "voice.wav", workdir / "sfx.wav"
    sf.write(voice_path, voice, VOICE_RATE, subtype="PCM_16")
    sf.write(fx_path, effects, sfx.RATE, subtype="PCM_16")
    return voice_path, fx_path


def chapters(scenes: list[Scene]) -> list[tuple[float, str]]:
    """(start time, title) for every chapter, from the scenes that open one."""
    out, start = [], 0.0
    for scene in scenes:
        if scene.chapter:
            out.append((start, scene.chapter))
        start += scene.duration
    return out


def _metadata(title: str, scenes: list[Scene], path: Path) -> None:
    """ffmpeg metadata file, so players show the chapters as chapters."""
    total = sum(s.duration for s in scenes)
    marks = chapters(scenes)
    esc = lambda s: "".join("\\" + c if c in "=;#\\\n" else c for c in s)
    lines = [";FFMETADATA1", f"title={esc(title)}"]
    for i, (start, name) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else total
        lines += ["[CHAPTER]", "TIMEBASE=1/1000", f"START={round(start * 1000)}", f"END={round(end * 1000)}",
                  f"title={esc(name)}"]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def mux(video: Path, voice: Path, effects: Path, dest: Path, title: str, scenes: list[Scene]) -> None:
    """Mix the two tracks and add them to the video without touching the picture."""
    meta = voice.with_name("chapters.txt")
    _metadata(title, scenes, meta)
    tmp = dest.with_name(dest.stem + ".tmp.mp4")
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(video), "-i", str(voice), "-i", str(effects),
         "-f", "ffmetadata", "-i", str(meta),
         "-filter_complex",
         "[1:a]aresample=48000[v];[v][2:a]amix=inputs=2:normalize=0:duration=longest,alimiter=limit=0.95[a]",
         "-map", "0:v", "-map", "[a]", "-map_metadata", "3", "-map_chapters", "3",
         "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", str(tmp)],
        check=True,
    )
    tmp.replace(dest)
