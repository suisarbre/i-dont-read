"""Turn a storyboard into timed scenes.

Narration drives the clock: every beat lasts as long as its spoken sentence, and the
visual actions and sound effects of a beat fire when its sentence (or a chosen word in it) is spoken.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from . import picture, source

FPS = 30
LEAD = 0.9        # entrance animation before the first beat
CARD_LEAD = 0.55  # same, on title cards
GAP = 0.32        # pause between sentences
TAIL = 0.6        # hold after the last sentence
HOLD = 1.3        # length of a beat with no narration
STAGGER = 0.18    # delay between items revealed together
ANTICIPATE = 0.08 # a cue fires this long before its word, so the eye is there when the word lands
CAPTION_CHARS = {"wide": 62, "tall": 36}
FORMATS = ("wide", "tall")

# Layout limits. Past these a scene stops being readable.
MAX_CODE_LINES = 16
MAX_CODE_COLS = 96
MAX_QUOTE_CHARS = 640
MAX_SAY_CHARS = 260

_CODE_LIKE = re.compile(r"[_\\<>{}\[\]=]|\w/\w|\w\(\)|\.(py|js|ts|json|md|cpp|hpp|h|rs|go|java|html|css|sh)\b")
_NOT_ACTIONS = {"say", "speak", "hold", "cues", "at"}


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


@dataclass
class _DryClip:
    samples: np.ndarray
    duration: float
    words: list = field(default_factory=list)


class DryNarrator:
    """Stands in for the voice when only checking a storyboard: guesses durations, makes no sound."""

    CHARS_PER_SECOND = 16.5

    def say(self, text: str) -> _DryClip:
        dur = max(0.8, len(text) / self.CHARS_PER_SECOND)
        return _DryClip(np.zeros(int(dur * 24000), dtype=np.float32), dur)


def _when(text: str, index: int, clip, exact: bool) -> float:
    """Seconds into the clip at which the character at `index` of the sentence is spoken.

    With one timing per written word the answer is exact. Otherwise (the voice merges some words,
    or `speak` differs from `say`) it is read off the real word timings by position in the sentence.
    """
    starts = [m.start() for m in re.finditer(r"\S+", text)]
    if not starts:
        return 0.0
    word = max(0, sum(1 for s in starts if s <= index) - 1)
    if not clip.words:
        return clip.duration * starts[word] / max(1, len(text))
    if exact and len(clip.words) == len(starts):
        return clip.words[word][0]
    letters = lambda s: sum(c.isalnum() for c in s)
    target = letters(text[:starts[word]]) / max(1, letters(text))
    total = sum(w[2] for w in clip.words)
    seen, best, best_gap = 0, clip.words[0], 2.0
    for w in clip.words:                               # the spoken word that starts nearest that far in
        gap = abs(seen / total - target)
        if gap < best_gap:
            best, best_gap = w, gap
        seen += w[2]
    return best[0]


class _Builder:
    """Carries what every scene needs: voice, theme, format, where files live, and collected warnings."""

    def __init__(self, root: Path, theme: str, narrator, captions: bool = True, fmt: str = "wide"):
        if fmt not in FORMATS:
            raise StoryboardError(f"format must be one of {', '.join(FORMATS)}, not {fmt!r}")
        self.root, self.theme, self.narrator, self.captions, self.fmt = root, theme, narrator, captions, fmt
        self.warnings: list[str] = []

    def warn(self, where: str, message: str) -> None:
        self.warnings.append(f"{where}: {message}")

    def scene(self, kind: str, kicker, spec: dict, **extra) -> Scene:
        heading = spec.get("heading")
        if heading and len(heading) > 60:
            self.warn(heading[:30] + "...", "heading is over 60 characters and may wrap badly")
        return Scene({"type": kind, "theme": self.theme, "format": self.fmt, "kicker": kicker, "heading": heading,
                      "sub": spec.get("sub"), "ops": [], **extra})


class _Clock:
    """Walks through the beats of one scene, speaking each and collecting captions."""

    def __init__(self, b: _Builder, scene: Scene, where: str, lead: float = LEAD):
        self.b, self.scene, self.where, self.t = b, scene, where, lead
        self.captions: list[dict] = []

    def _captions(self, text: str, start: float, clip, exact: bool) -> None:
        """Split a sentence into caption lines, each shown when its first word is spoken."""
        limit, chunks, cur, at = CAPTION_CHARS[self.b.fmt], [], "", 0
        for m in re.finditer(r"\S+", text):
            if cur and len(cur) + 1 + len(m.group()) > limit:
                chunks.append((at, cur))
                cur, at = m.group(), m.start()
            else:
                cur = f"{cur} {m.group()}".strip()
        if cur:
            chunks.append((at, cur))
        if len(chunks) > 1 and len(chunks[-1][1]) < 14:   # no orphan last line
            (a, first), (_, second) = chunks[-2:]
            chunks[-2:] = [(a, f"{first} {second}")]
        for i, (index, line) in enumerate(chunks):
            t = start if i == 0 else start + _when(text, index, clip, exact)
            self.captions.append({"t": round(t, 3), "text": line})
        self.captions.append({"t": round(start + clip.duration + 0.12, 3), "text": ""})

    def beat(self, beat: dict) -> list[tuple[float, dict, dict]]:
        """Place a beat. Returns (time, action, source) for the beat itself and for each cue inside its sentence.

        `action` is what to do (the beat or cue without its timing keys); `source` is the dict it came from.
        """
        start, text, clip = self.t, beat.get("say"), None
        self.started = round(start, 3)
        exact = not beat.get("speak")
        if text:
            if len(text) > MAX_SAY_CHARS:
                self.b.warn(self.where, f"a sentence is {len(text)} characters; split it into two beats")
            if exact and _CODE_LIKE.search(text):
                self.b.warn(self.where, f"narration has code-like text ({text[:44]!r}...); "
                                        'add "speak" with how it should be said aloud')
            clip = self.b.narrator.say(beat.get("speak") or text)
            self.scene.narration.append((start, clip.samples))
            self._captions(text, start, clip, exact)
            self.t = start + clip.duration + GAP
        else:
            self.t = start + float(beat.get("hold", HOLD))

        def at(phrase: str) -> float:
            if not text:
                raise StoryboardError(f'{self.where}: "at" needs a sentence in "say" to find {phrase!r} in')
            index = text.lower().find(phrase.lower())
            if index < 0:
                raise StoryboardError(f'{self.where}: "at" phrase {phrase!r} is not in the sentence {text[:50]!r}')
            return round(start + max(0.0, _when(text, index, clip, exact) - ANTICIPATE), 3)

        own = {k: v for k, v in beat.items() if k not in _NOT_ACTIONS}
        actions = [(at(beat["at"]) if beat.get("at") else round(start, 3), own, beat)]
        for cue in beat.get("cues", []):
            if not cue.get("at"):
                raise StoryboardError(f'{self.where}: every cue needs "at": a word or phrase from the sentence')
            actions.append((at(cue["at"]), {k: v for k, v in cue.items() if k != "at"}, cue))
        return sorted(actions, key=lambda a: a[0])

    def finish(self, minimum: float = 0.0) -> None:
        end = max(self.t - GAP + TAIL, minimum)
        self.scene.duration = math.ceil(end * FPS) / FPS
        self.scene.payload["captions"] = self.captions if self.b.captions else []
        self.scene.payload["ops"].sort(key=lambda op: op["t"])


class _Stage:
    """Reveals a list of items over the beats ("reveal": n means n items are visible from then on)."""

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


def _actions(spec: dict):
    """Every action in a scene (beats and their cues), in the order they are written."""
    for beat in spec.get("beats", []):
        yield beat
        yield from beat.get("cues", [])


def _staged(spec: dict) -> bool:
    return any("reveal" in act for act in _actions(spec))


def _card(b: _Builder, kicker, heading, sub=None, say=None, speak=None) -> Scene:
    scene = b.scene("title", kicker, {"heading": heading, "sub": sub})
    scene.sfx.append((0.12, "chime"))
    clock = _Clock(b, scene, heading, CARD_LEAD)
    if say:
        clock.beat({"say": say, "speak": speak})
    clock.finish(minimum=2.0)
    return scene


def _lines(b: _Builder, scene: Scene, spec: dict, where: str, index: dict[int, int]) -> None:
    """Beats shared by code and diff scenes. `index` maps a line number to its row on screen."""
    ops, rows = scene.payload["ops"], scene.payload["rows"]
    kinds = {"removed": {"-"}, "added": {"+"}, "changed": {"-", "+"}}
    clock = _Clock(b, scene, where)
    current, noted = None, False
    for i, beat in enumerate(spec.get("beats", [])):
        timed = clock.beat(beat)
        if noted and not beat.get("note"):             # a note belongs to its sentence
            ops.append({"op": "note", "t": clock.started, "text": None})
            noted = False
        for t, act, _ in timed:
            if "highlight" in act or "show" in act:
                if act.get("show") in kinds:
                    lit = [r for r, row in enumerate(rows) if row["kind"] in kinds[act["show"]]]
                    if not lit:
                        raise StoryboardError(f"{where} beat {i + 1}: there are no {act['show']} lines here")
                    span = ("lit", lit[0], lit[-1])
                    new_op = {"op": "lit", "t": t, "rows": lit}
                elif act.get("highlight") is None:
                    span, new_op = None, {"op": "clear", "t": t}
                else:
                    value = act["highlight"]
                    a, z = (value, value) if isinstance(value, int) else (value[0], value[-1])
                    if a not in index or z not in index or a > z:
                        raise StoryboardError(f"{where} beat {i + 1}: highlight {a}-{z} is outside the shown lines")
                    span = ("bar", index[a], index[z])
                    new_op = {"op": "highlight", "t": t, "from": index[a], "to": index[z]}
                if span != current:
                    ops.append(new_op)
                    if span:
                        scene.sfx.append((t, "tick"))
                    current = span
            if act.get("note") and current:
                ops.append({"op": "note", "t": t, "text": act["note"], "from": current[1], "to": current[2]})
                noted = True
    clock.finish()


def _check_rows(b: _Builder, rows: list[dict], where: str) -> None:
    if len(rows) > MAX_CODE_LINES:
        raise StoryboardError(f"{where} is {len(rows)} lines; show at most {MAX_CODE_LINES} per scene "
                              "(split it into two scenes)")
    widest = max(row["len"] for row in rows)
    if widest > MAX_CODE_COLS and b.fmt == "wide":
        b.warn(where, f"a line is {widest} columns wide; it will be cut off past about {MAX_CODE_COLS}")


def _expect(spec: dict, rows: list[dict], where: str) -> None:
    """`expect` pins the range: it must be on the first line shown, so any drift in line numbers is caught."""
    expect = spec.get("expect")
    if not expect:
        return
    first = str(spec["lines"][0])
    line = next((row["plain"] for row in rows if row["b"] == first), rows[0]["plain"])
    if expect not in line:
        raise StoryboardError(f"{where}: line {first} is {line.strip()[:60]!r}, not the expected {expect!r}; "
                              "the file has changed, so fix the line range")


def _code(b: _Builder, spec: dict, kicker: str) -> Scene:
    first, last = spec["lines"]
    where = f"{spec['file']}:{first}-{last}"
    rows = source.extract(b.root, spec["file"], first, last)
    _expect(spec, rows, where)
    _check_rows(b, rows, where)
    scene = b.scene("code", kicker, {**spec, "sub": f"{spec['file']}  ·  lines {first}–{last}"}, rows=rows)
    scene.sfx.append((0.0, "whoosh"))
    _lines(b, scene, spec, where, {first + i: i for i in range(len(rows))})
    return scene


def _diff(b: _Builder, spec: dict, kicker: str) -> Scene:
    first, last = spec["lines"]
    name = spec.get("file") or spec["after"]
    where = f"{name}:{first}-{last} (diff)"
    rows, label = source.diff(b.root, spec, first, last)
    _expect(spec, rows, where)
    _check_rows(b, rows, where)
    scene = b.scene("diff", kicker, {**spec, "sub": label}, rows=rows)
    scene.sfx.append((0.0, "whoosh"))
    _lines(b, scene, spec, where, {int(row["b"]): i for i, row in enumerate(rows) if row["b"]})
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
    ids: dict[int, list[int]] = {}                                        # action -> its mark ids
    for act in _actions(spec):
        phrases = act.get("mark") or []
        for phrase in [phrases] if isinstance(phrases, str) else phrases:
            needle = source.clean(phrase)
            for p, para in enumerate(paragraphs):
                at = para.find(needle)
                if at >= 0:
                    if any(s < at + len(needle) and at < e for s, e, _ in found[p]):
                        raise StoryboardError(f"{where}: mark {phrase!r} overlaps an earlier mark")
                    mark_id = sum(len(f) for f in found)
                    found[p].append((at, at + len(needle), mark_id))
                    ids.setdefault(id(act), []).append(mark_id)
                    break
            else:
                raise StoryboardError(f"{where}: mark {phrase!r} is not in the quoted text; "
                                      "marks must be copied exactly from the source")

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
    for beat in spec.get("beats", []):
        for t, _, src in clock.beat(beat):
            for j, mid in enumerate(ids.get(id(src), [])):
                at = round(t + (0.1 if src is beat and not beat.get("at") else 0.0) + j * 0.55, 3)
                dur = round(min(1.1, max(0.35, lengths[mid] / 45)), 3)
                scene.payload["ops"].append({"op": "mark", "t": at, "id": mid, "dur": dur})
                scene.sfx.append((at, "mark"))
    clock.finish()
    return scene


def _reveals(b: _Builder, scene: Scene, spec: dict, where: str, count: int, key: str, focus: bool = False) -> None:
    """Beats for scenes made of a list of items: flow, compare, stats, steps."""
    clock = _Clock(b, scene, where)
    stage = _Stage(scene, count, key, _staged(spec))
    focused = None
    for beat in spec.get("beats", []):
        for t, act, src in clock.beat(beat):
            if "reveal" in act:
                stage.upto(act["reveal"], t)
            if not focus:
                continue
            if "focus" in act:
                target = None if act["focus"] is None else int(act["focus"]) - 1
            else:
                target = None if src is beat else focused   # a new sentence with no focus drops the ring
            if target is not None and not 0 <= target < count:
                raise StoryboardError(f"{where}: focus {target + 1} is not one of the {count} nodes")
            if target != focused:
                scene.payload["ops"].append({"op": "focus", "t": round(t + 0.05, 3), "node": target})
                focused = target
    stage.upto(count, clock.t)                         # never end with hidden items
    clock.finish()


def _flow(b: _Builder, spec: dict, kicker: str) -> Scene:
    nodes = spec["nodes"]
    where = spec.get("heading") or "flow"
    if not 2 <= len(nodes) <= 6:
        raise StoryboardError(f"{where}: a flow needs 2 to 6 nodes, not {len(nodes)}")
    limit = 12 if len(nodes) >= 5 and b.fmt == "wide" else 18
    for node in nodes:
        if len(node["label"]) > limit:
            b.warn(where, f"node label {node['label']!r} is over {limit} characters and may wrap")
    scene = b.scene("flow", kicker, spec, nodes=nodes)
    scene.sfx.append((0.0, "whoosh"))
    _reveals(b, scene, spec, where, len(nodes), "node", focus=True)
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
    _reveals(b, scene, spec, where, rows, "row")
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
    _reveals(b, scene, spec, where, len(items), "item")
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
    _reveals(b, scene, spec, where, len(items), "item")
    return scene


def _image(b: _Builder, spec: dict, kicker: str) -> Scene:
    where = spec.get("heading") or spec.get("file") or spec.get("url") or "image"
    if not (spec.get("file") or spec.get("url")):
        raise StoryboardError(f'{where}: an image scene needs "file" (an image or PDF) or "url" (a web page)')
    regions = [act[key] for act in _actions(spec) for key in ("zoom", "box") if act.get(key)]
    finds = sorted({r["find"] for r in regions if isinstance(r, dict)})
    pic = picture.resolve(b.root, spec, finds)

    def region(value) -> list[float]:
        if isinstance(value, dict):
            hit = pic["found"].get(value["find"])
            if hit is None:
                raise StoryboardError(f"{where}: the text {value['find']!r} is not on the page; "
                                      "it must be copied exactly from what is shown")
            pad = 0.006                                 # a little air around the words, the same on every side
            x, y, w, h = hit
            py = pad * pic["iw"] / pic["ih"]
            x0, y0, x1, y1 = max(0, x - pad), max(0, y - py), min(1, x + w + pad), min(1, y + h + py)
            return [round(v, 5) for v in (x0, y0, x1 - x0, y1 - y0)]
        if len(value) != 4 or not all(0 <= v <= 1 for v in value):
            raise StoryboardError(f"{where}: a region is [x, y, width, height], each from 0 to 1, not {value!r}")
        return list(value)

    boxes: list[list[float]] = []
    scene = b.scene("image", kicker, {**spec, "sub": spec.get("sub") or pic["label"]},
                    src=pic["path"].as_uri(), iw=pic["iw"], ih=pic["ih"], stamp=pic["stamp"], boxes=boxes)
    ops = scene.payload["ops"]
    scene.sfx.append((0.0, "whoosh"))
    clock = _Clock(b, scene, where)
    for beat in spec.get("beats", []):
        for t, act, _ in clock.beat(beat):
            if "zoom" in act:
                ops.append({"op": "cam", "t": t, "region": region(act["zoom"]) if act["zoom"] else None})
                scene.sfx.append((t, "zoom"))
            if "box" in act:
                if act["box"]:
                    boxes.append(region(act["box"]))
                    ops.append({"op": "box", "t": round(t + (0.5 if "zoom" in act else 0.0), 3), "id": len(boxes) - 1})
                    scene.sfx.append((ops[-1]["t"], "tick"))
                else:
                    ops.append({"op": "box", "t": t, "id": -1})
    clock.finish()
    return scene


def _overview(b: _Builder, title: str, chapters: list[dict], intro: dict) -> Scene:
    """Opening card that lists the chapters, so the outline is watched instead of read."""
    scene = b.scene("steps", "In this video", {"heading": title}, items=[{"title": c["title"]} for c in chapters])
    scene.sfx.append((0.12, "chime"))
    for j in range(len(chapters)):
        scene.payload["ops"].append({"op": "reveal", "t": round(0.6 + j * 0.22, 3), "item": j})
    clock = _Clock(b, scene, title, 0.75)
    if intro.get("say"):
        clock.beat({"say": intro["say"], "speak": intro.get("speak")})
    clock.finish(minimum=2.6 + 0.35 * len(chapters))
    return scene


SCENES = {"code": _code, "diff": _diff, "quote": _quote, "image": _image, "flow": _flow, "compare": _compare,
          "stats": _stats, "steps": _steps}
OVERVIEW_FROM = 3   # videos with this many chapters open with a card that lists them


def build(storyboard: dict, root: Path, theme: str, narrator, captions: bool = True,
          fmt: str = "wide") -> tuple[list[Scene], list[str]]:
    """All scenes of the video in order, plus warnings about things that may not read well."""
    b = _Builder(root, theme, narrator, captions, fmt)
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
