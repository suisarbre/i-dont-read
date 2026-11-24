"""Turn a storyboard into timed scenes.

Narration drives the clock: every beat lasts as long as its spoken sentence, and the
visual actions and sound effects of a beat fire when its sentence starts.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from . import source

FPS = 30
LEAD = 0.9        # entrance animation before the first beat
CARD_LEAD = 0.55  # same, on title cards
GAP = 0.32        # pause between sentences
TAIL = 0.6        # hold after the last sentence
HOLD = 1.3        # length of a beat with no narration
STAGGER = 0.18    # delay between items revealed together
CAPTION_CHARS = 62

# Layout limits. Past these a scene stops being readable at 1080p.
MAX_CODE_LINES = 16
MAX_CODE_COLS = 96
MAX_QUOTE_CHARS = 640
MAX_SAY_CHARS = 260

_CODE_LIKE = re.compile(r"[_\\<>{}\[\]=]|\w/\w|\w\(\)|\.(py|js|ts|json|md|cpp|hpp|h|rs|go|java|html|css|sh)\b")


class StoryboardError(ValueError):
    """The storyboard asks for something that cannot be shown truthfully or legibly."""


@dataclass
class Scene:
    payload: dict                                   # what the player draws
    duration: float = 0.0                           # seconds, a whole number of frames
    narration: list[tuple[float, np.ndarray]] = field(default_factory=list)  # (time in scene, samples)
    sfx: list[tuple[float, str]] = field(default_factory=list)               # (time in scene, effect)
    chapter: str | None = None                      # set on the scene that opens a chapter

    @property
    def frames(self) -> int:
        return round(self.duration * FPS)


class DryNarrator:
    """Stands in for the voice when only checking a storyboard: guesses durations, makes no sound."""

    CHARS_PER_SECOND = 16.5

    def say(self, text: str) -> tuple[np.ndarray, float]:
        dur = max(0.8, len(text) / self.CHARS_PER_SECOND)
        return np.zeros(int(dur * 24000), dtype=np.float32), dur


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


class _Builder:
    """Carries what every scene needs: voice, theme, where files live, and collected warnings."""

    def __init__(self, root: Path, theme: str, narrator, captions: bool = True):
        self.root, self.theme, self.narrator, self.captions = root, theme, narrator, captions
        self.warnings: list[str] = []

    def warn(self, where: str, message: str) -> None:
        self.warnings.append(f"{where}: {message}")

    def scene(self, kind: str, kicker, spec: dict, **extra) -> Scene:
        heading = spec.get("heading")
        if heading and len(heading) > 60:
            self.warn(heading[:30] + "...", "heading is over 60 characters and may wrap badly")
        return Scene({"type": kind, "theme": self.theme, "kicker": kicker, "heading": heading,
                      "sub": spec.get("sub"), "ops": [], **extra})


class _Clock:
    """Walks through the beats of one scene, speaking each and collecting captions."""

    def __init__(self, b: _Builder, scene: Scene, where: str, lead: float = LEAD):
        self.b, self.scene, self.where, self.t = b, scene, where, lead
        self.captions: list[dict] = []

    def beat(self, beat: dict) -> float:
        """Place a beat; returns its start time."""
        start = self.t
        text = beat.get("say")
        if text:
            if len(text) > MAX_SAY_CHARS:
                self.b.warn(self.where, f"a sentence is {len(text)} characters; split it into two beats")
            if not beat.get("speak") and _CODE_LIKE.search(text):
                self.b.warn(self.where, f"narration has code-like text ({text[:44]!r}...); "
                                        'add "speak" with how it should be said aloud')
            samples, dur = self.b.narrator.say(beat.get("speak") or text)
            self.scene.narration.append((start, samples))
            self.captions += _caption_chunks(text, start, dur)
            self.captions.append({"t": round(start + dur + 0.12, 3), "text": ""})
            self.t = start + dur + GAP
        else:
            self.t = start + float(beat.get("hold", HOLD))
        return round(start, 3)

    def finish(self, minimum: float = 0.0) -> None:
        end = max(self.t - GAP + TAIL, minimum)
        self.scene.duration = math.ceil(end * FPS) / FPS
        self.scene.payload["captions"] = self.captions if self.b.captions else []
        self.scene.payload["ops"].sort(key=lambda op: op["t"])


class _Stage:
    """Reveals a list of items over the beats ("reveal": n means n items are visible from this beat on)."""

    def __init__(self, scene: Scene, count: int, key: str, staged: bool):
        self.scene, self.count, self.key, self.visible = scene, count, key, 0
        if not staged:                                # nothing staged: show everything on entrance
            self.upto(count, 0.45)

    def upto(self, n: int, t: float) -> None:
        n = min(int(n), self.count)
        for j, item in enumerate(range(self.visible, n)):
            at = round(t + j * STAGGER, 3)
            self.scene.payload["ops"].append({"op": "reveal", "t": at, self.key: item})
            self.scene.sfx.append((at, "pop"))
        self.visible = max(self.visible, n)


def _card(b: _Builder, kicker, heading, sub=None, say=None, speak=None) -> Scene:
    scene = Scene({"type": "title", "theme": b.theme, "kicker": kicker, "heading": heading, "sub": sub, "ops": []})
    scene.sfx.append((0.12, "chime"))
    clock = _Clock(b, scene, heading, CARD_LEAD)
    if say:
        clock.beat({"say": say, "speak": speak})
    clock.finish(minimum=2.0)
    return scene


def _span(value, first: int, last: int, where: str) -> tuple[int, int]:
    a, b = (value, value) if isinstance(value, int) else (value[0], value[-1])
    if not (first <= a <= b <= last):
        raise StoryboardError(f"{where}: highlight {a}-{b} is outside the shown lines {first}-{last}")
    return a, b


def _code(b: _Builder, spec: dict, kicker: str) -> Scene:
    first, last = spec["lines"]
    where = f"{spec['file']}:{first}-{last}"
    src = source.extract(b.root, spec["file"], first, last)
    expect = spec.get("expect")                       # guards against line numbers drifting after an edit
    if expect and not any(expect in line for line in src["plain"]):
        raise StoryboardError(f"{where} does not contain {expect!r}; fix the line range")
    if last - first + 1 > MAX_CODE_LINES:
        raise StoryboardError(f"{where} is {last - first + 1} lines; show at most {MAX_CODE_LINES} per scene "
                              "(split it into two scenes)")
    widest = max(len(line) for line in src["plain"])
    if widest > MAX_CODE_COLS:
        b.warn(where, f"a line is {widest} columns wide; it will be cut off past about {MAX_CODE_COLS}")

    scene = b.scene("code", kicker, {**spec, "sub": f"{spec['file']}  ·  lines {first}–{last}"},
                    first=first, lines=src["lines"], plain=src["plain"])
    ops = scene.payload["ops"]
    scene.sfx.append((0.0, "whoosh"))
    clock = _Clock(b, scene, where)
    current, noted = None, False
    for i, beat in enumerate(spec.get("beats", [])):
        t = clock.beat(beat)
        if "highlight" in beat:
            span = None if beat["highlight"] is None else _span(beat["highlight"], first, last, f"{where} beat {i + 1}")
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


def _quote(b: _Builder, spec: dict, kicker: str) -> Scene:
    first, last = spec["lines"]
    where = f"{spec['file']}:{first}-{last}"
    paragraphs = source.excerpt(b.root, spec["file"], first, last)
    size = sum(len(p) for p in paragraphs)
    if size > MAX_QUOTE_CHARS:
        raise StoryboardError(f"{where} is {size} characters of text; quote at most {MAX_QUOTE_CHARS} per scene")

    # Every marked phrase must be found, word for word, in the text that is actually on screen.
    found: list[list[tuple[int, int, int]]] = [[] for _ in paragraphs]   # per paragraph: (start, end, mark id)
    schedule: list[list[int]] = []                                        # per beat: mark ids
    mark_id = 0
    beats = spec.get("beats", [])
    for i, beat in enumerate(beats):
        phrases = beat.get("mark") or []
        phrases = [phrases] if isinstance(phrases, str) else phrases
        ids = []
        for phrase in phrases:
            needle = source.clean(phrase)
            for p, para in enumerate(paragraphs):
                at = para.find(needle)
                if at >= 0:
                    if any(s < at + len(needle) and at < e for s, e, _ in found[p]):
                        raise StoryboardError(f"{where} beat {i + 1}: mark {phrase!r} overlaps an earlier mark")
                    found[p].append((at, at + len(needle), mark_id))
                    break
            else:
                raise StoryboardError(f"{where} beat {i + 1}: mark {phrase!r} is not in the quoted text; "
                                      "marks must be copied exactly from the source")
            ids.append(mark_id)
            mark_id += 1
        schedule.append(ids)

    segments, lengths = [], {}
    for para, spans in zip(paragraphs, found):
        parts, pos = [], 0
        for s, e, mid in sorted(spans):
            if s > pos:
                parts.append({"text": para[pos:s]})
            parts.append({"text": para[s:e], "mark": mid})
            lengths[mid] = e - s
            pos = e
        if pos < len(para):
            parts.append({"text": para[pos:]})
        segments.append(parts)

    scene = b.scene("quote", kicker, {**spec, "sub": f"{spec['file']}  ·  lines {first}–{last}"}, paragraphs=segments)
    scene.sfx.append((0.0, "whoosh"))
    clock = _Clock(b, scene, where)
    for ids, beat in zip(schedule, beats):
        t = clock.beat(beat)
        for j, mid in enumerate(ids):
            at = round(t + 0.1 + j * 0.55, 3)
            dur = round(min(1.1, max(0.35, lengths[mid] / 45)), 3)
            scene.payload["ops"].append({"op": "mark", "t": at, "id": mid, "dur": dur})
            scene.sfx.append((at, "mark"))
    clock.finish()
    return scene


def _flow(b: _Builder, spec: dict, kicker: str) -> Scene:
    nodes = spec["nodes"]
    where = spec.get("heading") or "flow"
    if not 2 <= len(nodes) <= 6:
        raise StoryboardError(f"{where}: a flow needs 2 to 6 nodes, not {len(nodes)}")
    limit = 12 if len(nodes) >= 5 else 18
    for node in nodes:
        if len(node["label"]) > limit:
            b.warn(where, f"node label {node['label']!r} is over {limit} characters and may wrap")
    scene = b.scene("flow", kicker, spec, nodes=nodes)
    scene.sfx.append((0.0, "whoosh"))
    beats = spec.get("beats", [])
    clock = _Clock(b, scene, where)
    stage = _Stage(scene, len(nodes), "node", any("reveal" in x for x in beats))
    focused = None
    for beat in beats:
        t = clock.beat(beat)
        if "reveal" in beat:
            stage.upto(beat["reveal"], t)
        focus = beat.get("focus")
        focus = None if focus is None else int(focus) - 1
        if focus is not None and not 0 <= focus < len(nodes):
            raise StoryboardError(f"{where}: focus {focus + 1} is not one of the {len(nodes)} nodes")
        if focus != focused:
            scene.payload["ops"].append({"op": "focus", "t": round(t + 0.05, 3), "node": focus})
            focused = focus
    stage.upto(len(nodes), clock.t)                   # never end with hidden items
    clock.finish()
    return scene


def _compare(b: _Builder, spec: dict, kicker: str) -> Scene:
    columns = spec["columns"]
    where = spec.get("heading") or "compare"
    if len(columns) != 2:
        raise StoryboardError(f"{where}: a comparison has exactly 2 columns, not {len(columns)}")
    rows = max(len(c["points"]) for c in columns)
    if not 1 <= rows <= 5:
        raise StoryboardError(f"{where}: a comparison shows 1 to 5 rows, not {rows}")
    for c in columns:
        for point in c["points"]:
            if len(point) > 80:
                b.warn(where, f"point {point[:30]!r}... is over 80 characters")
    scene = b.scene("compare", kicker, spec, columns=columns)
    scene.sfx.append((0.0, "whoosh"))
    beats = spec.get("beats", [])
    clock = _Clock(b, scene, where)
    stage = _Stage(scene, rows, "row", any("reveal" in x for x in beats))
    for beat in beats:
        t = clock.beat(beat)
        if "reveal" in beat:
            stage.upto(beat["reveal"], t)
    stage.upto(rows, clock.t)
    clock.finish()
    return scene


def _stats(b: _Builder, spec: dict, kicker: str) -> Scene:
    where = spec.get("heading") or "stats"
    items = [{**item, "value": str(item["value"])} for item in spec["items"]]
    if not 1 <= len(items) <= 4:
        raise StoryboardError(f"{where}: show 1 to 4 numbers, not {len(items)}")
    for item in items:
        if len(item["value"]) > 10:
            b.warn(where, f"value {item['value']!r} is over 10 characters; move words into the label")
    scene = b.scene("stats", kicker, spec, items=items)
    scene.sfx.append((0.0, "whoosh"))
    beats = spec.get("beats", [])
    clock = _Clock(b, scene, where)
    stage = _Stage(scene, len(items), "item", any("reveal" in x for x in beats))
    for beat in beats:
        t = clock.beat(beat)
        if "reveal" in beat:
            stage.upto(beat["reveal"], t)
    stage.upto(len(items), clock.t)
    clock.finish()
    return scene


def _steps(b: _Builder, spec: dict, kicker: str) -> Scene:
    items = spec["items"]
    where = spec.get("heading") or "steps"
    if not 1 <= len(items) <= 6:
        raise StoryboardError(f"{where}: show 1 to 6 steps, not {len(items)}")
    for item in items:
        if len(item["title"]) > 48:
            b.warn(where, f"step title {item['title'][:30]!r}... is over 48 characters")
        if len(item.get("cmd") or "") > 48:
            b.warn(where, f"command {item['cmd'][:30]!r}... is over 48 characters and may not fit")
    scene = b.scene("steps", kicker, spec, items=items)
    scene.sfx.append((0.0, "whoosh"))
    beats = spec.get("beats", [])
    clock = _Clock(b, scene, where)
    stage = _Stage(scene, len(items), "item", any("reveal" in x for x in beats))
    for beat in beats:
        t = clock.beat(beat)
        if "reveal" in beat:
            stage.upto(beat["reveal"], t)
    stage.upto(len(items), clock.t)
    clock.finish()
    return scene


def _overview(b: _Builder, title: str, chapters: list[dict], intro: dict) -> Scene:
    """Opening card that lists the chapters, so the outline is watched instead of read."""
    scene = Scene({"type": "steps", "theme": b.theme, "kicker": "In this video", "heading": title, "sub": None,
                   "items": [{"title": c["title"]} for c in chapters], "ops": []})
    scene.sfx.append((0.12, "chime"))
    for j in range(len(chapters)):
        scene.payload["ops"].append({"op": "reveal", "t": round(0.6 + j * 0.22, 3), "item": j})
    clock = _Clock(b, scene, title, 0.75)
    if intro.get("say"):
        clock.beat({"say": intro["say"], "speak": intro.get("speak")})
    clock.finish(minimum=2.6 + 0.35 * len(chapters))
    return scene


SCENES = {"code": _code, "quote": _quote, "flow": _flow, "compare": _compare, "stats": _stats, "steps": _steps}
OVERVIEW_FROM = 3   # videos with this many chapters open with a card that lists them


def build(storyboard: dict, root: Path, theme: str, narrator, captions: bool = True) -> tuple[list[Scene], list[str]]:
    """All scenes of the video in order, plus warnings about things that may not read well."""
    b = _Builder(root, theme, narrator, captions)
    scenes: list[Scene] = []
    if not storyboard.get("chapters"):
        raise StoryboardError("the storyboard has no chapters")
    intro = storyboard.get("intro")
    if len(storyboard["chapters"]) >= OVERVIEW_FROM:
        if not storyboard.get("title"):
            raise StoryboardError('the storyboard needs a "title"')
        scenes.append(_overview(b, storyboard["title"], storyboard["chapters"], intro or {}))
        scenes[-1].chapter = "Overview"
    elif intro:
        scenes.append(_card(b, intro.get("kicker"), storyboard["title"], intro.get("sub"),
                            intro.get("say"), intro.get("speak")))
        scenes[-1].chapter = "Intro"
    for n, chapter in enumerate(storyboard["chapters"], 1):
        card = _card(b, f"Chapter {n}", chapter["title"], chapter.get("sub"), chapter.get("say"), chapter.get("speak"))
        card.chapter = chapter["title"]
        scenes.append(card)
        if not chapter.get("scenes"):
            raise StoryboardError(f"chapter {n} ({chapter['title']}) has no scenes")
        kicker = f"{n} · {chapter['title']}"
        for spec in chapter["scenes"]:
            make = SCENES.get(spec.get("type"))
            if not make:
                raise StoryboardError(f"unknown scene type {spec.get('type')!r}; use one of {', '.join(SCENES)}")
            try:
                scenes.append(make(b, spec, kicker))
            except KeyError as missing:
                raise StoryboardError(f"chapter {n}, {spec['type']} scene: missing field {missing}") from None
    return scenes, b.warnings
