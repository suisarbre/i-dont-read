"""Turn a storyboard into timed scenes.

Narration drives the clock: every beat lasts as long as its spoken sentence, and the
visual actions and sound effects of a beat fire when its sentence starts.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from . import source
from .tts import Narrator

FPS = 30
LEAD = 0.9        # entrance animation before the first beat
CARD_LEAD = 0.55  # same, on title cards
GAP = 0.32        # pause between sentences
TAIL = 0.6        # hold after the last sentence
HOLD = 1.3        # length of a beat with no narration
REVEAL_STAGGER = 0.18
CAPTION_CHARS = 62


@dataclass
class Scene:
    payload: dict                                   # what the player draws
    duration: float = 0.0                           # seconds, a whole number of frames
    narration: list[tuple[float, np.ndarray]] = field(default_factory=list)  # (time in scene, samples)
    sfx: list[tuple[float, str]] = field(default_factory=list)               # (time in scene, effect)

    @property
    def frames(self) -> int:
        return round(self.duration * FPS)


def _caption_chunks(text: str, start: float, dur: float) -> list[dict]:
    """Split a sentence into caption lines, timed by their share of the characters."""
    words, chunks, cur = text.split(), [], ""
    for w in words:
        if cur and len(cur) + 1 + len(w) > CAPTION_CHARS:
            chunks.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        chunks.append(cur)
    if len(chunks) > 1 and len(chunks[-1]) < 14:      # no orphan last line
        chunks[-2:] = [f"{chunks[-2]} {chunks[-1]}"]
    total = sum(len(c) for c in chunks) or 1
    out, t = [], start
    for c in chunks:
        out.append({"t": round(t, 3), "text": c})
        t += dur * len(c) / total
    return out


class _Clock:
    """Walks through the beats of one scene, speaking each and collecting captions."""

    def __init__(self, scene: Scene, narrator: Narrator, lead: float):
        self.scene, self.narrator, self.t = scene, narrator, lead
        self.captions: list[dict] = []

    def beat(self, beat: dict) -> float:
        """Place a beat; returns its start time."""
        start = self.t
        text = beat.get("say")
        if text:
            samples, dur = self.narrator.say(beat.get("speak") or text)
            self.scene.narration.append((start, samples))
            self.captions += _caption_chunks(text, start, dur)
            self.captions.append({"t": round(start + dur + 0.12, 3), "text": ""})
            self.t = start + dur + GAP
        else:
            self.t = start + float(beat.get("hold", HOLD))
        return start

    def finish(self, minimum: float = 0.0) -> None:
        end = max(self.t - GAP + TAIL, minimum)
        self.scene.duration = math.ceil(end * FPS) / FPS
        self.scene.payload["captions"] = self.captions


def _card(narrator, theme, kicker, heading, sub=None, say=None, speak=None, sound="chime") -> Scene:
    scene = Scene({"type": "title", "theme": theme, "kicker": kicker, "heading": heading, "sub": sub})
    scene.sfx.append((0.12, sound))
    clock = _Clock(scene, narrator, CARD_LEAD)
    if say:
        clock.beat({"say": say, "speak": speak})
    clock.finish(minimum=2.0)
    return scene


def _span(value, first: int, last: int, where: str) -> tuple[int, int]:
    a, b = (value, value) if isinstance(value, int) else (value[0], value[-1])
    if not (first <= a <= b <= last):
        raise ValueError(f"{where}: highlight {a}-{b} is outside the shown lines {first}-{last}")
    return a, b


def _code(spec: dict, root: Path, narrator: Narrator, theme: str, kicker: str) -> Scene:
    first, last = spec["lines"]
    src = source.extract(root, spec["file"], first, last)
    expect = spec.get("expect")                       # guards against line numbers drifting after an edit
    if expect and not any(expect in line for line in src["plain"]):
        raise ValueError(f"{spec['file']} lines {first}-{last} no longer contain {expect!r}; update the line range")
    scene = Scene({
        "type": "code", "theme": theme, "kicker": kicker, "heading": spec.get("heading"),
        "sub": f"{spec['file']}  ·  lines {first}–{last}",
        "first": first, "lines": src["lines"], "plain": src["plain"], "ops": [],
    })
    ops = scene.payload["ops"]
    scene.sfx.append((0.0, "whoosh"))
    clock = _Clock(scene, narrator, LEAD)
    current, noted = None, False
    for i, beat in enumerate(spec.get("beats", [])):
        t = round(clock.beat(beat), 3)
        if "highlight" in beat:
            span = None if beat["highlight"] is None else _span(
                beat["highlight"], first, last, f"{spec['file']} beat {i + 1}")
            if span != current:
                if span is None:
                    ops.append({"op": "clear", "t": t})
                else:
                    ops.append({"op": "highlight", "t": t, "from": span[0], "to": span[1]})
                    scene.sfx.append((t, "tick"))
                current = span
        if beat.get("note") and current:
            ops.append({"op": "note", "t": t, "text": beat["note"], "from": current[0], "to": current[1]})
            noted = True
        elif noted:
            ops.append({"op": "note", "t": t, "text": None})
            noted = False
    clock.finish()
    return scene


def _flow(spec: dict, narrator: Narrator, theme: str, kicker: str) -> Scene:
    nodes = spec["nodes"]
    scene = Scene({
        "type": "flow", "theme": theme, "kicker": kicker, "heading": spec.get("heading"),
        "sub": spec.get("sub"), "nodes": nodes, "ops": [],
    })
    ops = scene.payload["ops"]
    scene.sfx.append((0.0, "whoosh"))
    beats = spec.get("beats", [])
    clock = _Clock(scene, narrator, LEAD)
    visible, focused = 0, None

    def reveal(upto: int, t: float) -> None:
        nonlocal visible
        for j, node in enumerate(range(visible, min(upto, len(nodes)))):
            at = round(t + j * REVEAL_STAGGER, 3)
            ops.append({"op": "reveal", "t": at, "node": node})
            scene.sfx.append((at, "pop"))
        visible = max(visible, min(upto, len(nodes)))

    if not any("reveal" in b for b in beats):         # nothing staged: show the whole diagram up front
        reveal(len(nodes), 0.45)
    for beat in beats:
        t = round(clock.beat(beat), 3)
        if "reveal" in beat:
            reveal(int(beat["reveal"]), t)
        focus = beat.get("focus")
        focus = None if focus is None else int(focus) - 1
        if focus != focused:
            ops.append({"op": "focus", "t": round(t + 0.05, 3), "node": focus})
            focused = focus
    reveal(len(nodes), clock.t)                       # never end with hidden nodes
    ops.sort(key=lambda op: op["t"])
    clock.finish()
    return scene


def build(storyboard: dict, root: Path, theme: str, narrator: Narrator) -> list[Scene]:
    """All scenes of the video, in order, with timings, narration and sound effects."""
    scenes: list[Scene] = []
    intro = storyboard.get("intro")
    if intro:
        scenes.append(_card(narrator, theme, intro.get("kicker"), storyboard["title"], intro.get("sub"),
                            intro.get("say"), intro.get("speak")))
    for n, chapter in enumerate(storyboard["chapters"], 1):
        scenes.append(_card(narrator, theme, f"Chapter {n}", chapter["title"], chapter.get("sub"),
                            chapter.get("say"), chapter.get("speak")))
        kicker = f"{n} · {chapter['title']}"
        for spec in chapter.get("scenes", []):
            kind = spec["type"]
            if kind == "code":
                scenes.append(_code(spec, root, narrator, theme, kicker))
            elif kind == "flow":
                scenes.append(_flow(spec, narrator, theme, kicker))
            else:
                raise ValueError(f"unknown scene type: {kind}")
    return scenes
