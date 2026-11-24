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

from . import picture, plot, source, texmath

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
MAX_CODE_COLS = 120   # the font shrinks to fit the longest line; past this it is too small to read
MAX_QUOTE_CHARS = 640
MAX_SAY_CHARS = 260
MAX_MATH_LINES = 4
MAX_TABLE_COLS = 6
MAX_TABLE_ROWS = 8
MAX_CURVES = 3
MAX_CELL_CHARS = 40

_CODE_LIKE = re.compile(r"[_\\<>{}\[\]=$^]|\w/\w|\w\(\)|\.(py|js|ts|json|md|cpp|hpp|h|rs|go|java|html|css|sh)\b")
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
    stops: list[float] = field(default_factory=list)   # when something changes on screen (beats and cues)

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
        self.noted: set[str] = set()
        self.math_default = True
        self.tex: list[dict] = []      # every LaTeX expression on screen, checked with KaTeX once all scenes are built

    def rich(self, value, on: bool, where: str):
        """Text that may hold $...$ math: the string itself, or segments [{"text"} | {"tex", "display", "raw"}]."""
        if not isinstance(value, str) or not value or not on:
            return value
        found = texmath.spans(value)
        if not found:
            return texmath.unescape(value)
        segs, pos = [], 0
        for start, end, tex, display in found:
            if start > pos:
                segs.append({"text": texmath.unescape(value[pos:start])})
            seg = {"tex": tex, "display": display, "raw": value[start:end]}
            self.tex.append({"where": where, "tex": tex, "display": display, "seg": seg, "strict": False})
            segs.append(seg)
            pos = end
        if pos < len(value):
            segs.append({"text": texmath.unescape(value[pos:])})
        return segs

    def warn(self, where: str, message: str) -> None:
        self.warnings.append(f"{where}: {message}")

    def scene(self, kind: str, kicker, spec: dict, sub_is_source: bool = False, **extra) -> Scene:
        heading = spec.get("heading")
        if heading and len(heading) > 60:
            self.warn(heading[:30] + "...", "heading is over 60 characters and may wrap badly")
        on, where = _math_on(self, spec), heading or kind
        sub = spec.get("sub") if sub_is_source else self.rich(spec.get("sub"), on, where)
        return Scene({"type": kind, "theme": self.theme, "format": self.fmt, "kicker": kicker,
                      "heading": self.rich(heading, on, where), "sub": sub, "ops": [], **extra})


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
        self.scene.stops.extend(t for t, _, _ in actions)
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


def _math_on(b: "_Builder", spec: dict) -> bool:
    return bool(spec.get("math", b.math_default))


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
        gone = sum(1 for row in rows if row["kind"] == "-")
        detail = f" on screen ({len(rows) - gone} from the new file plus {gone} removed)" if gone else ""
        raise StoryboardError(f"{where} is {len(rows)} lines{detail}; show at most {MAX_CODE_LINES} per scene "
                              "(split it into two scenes)")
    widest = max(row["len"] for row in rows)
    limit = MAX_CODE_COLS - (6 if any(row["kind"] for row in rows) else 0)   # a diff spends columns on its gutter
    if widest > limit and b.fmt == "wide":
        b.warn(where, f"a line is {widest} columns wide, so the code will be small (over {limit}); "
                      "show fewer or shorter lines")


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


def _where(spec: dict, first: int, last: int) -> str:
    """The line under a heading that says exactly what is on screen: file, lines, and the git ref if not the current file."""
    at = f"  ·  as of {spec['ref']}" if spec.get("ref") else ""
    return f"{spec['file']}  ·  {f'line {first}' if first == last else f'lines {first}–{last}'}{at}"


def _code(b: _Builder, spec: dict, kicker: str) -> Scene:
    first, last = spec["lines"]
    where = f"{spec['file']}:{first}-{last}"
    rows = source.extract(b.root, spec["file"], first, last, spec.get("ref"), spec.get("encoding"))
    _expect(spec, rows, where)
    _check_rows(b, rows, where)
    scene = b.scene("code", kicker, {**spec, "sub": _where(spec, first, last)}, sub_is_source=True, rows=rows)
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
    scene = b.scene("diff", kicker, {**spec, "sub": label}, sub_is_source=True, rows=rows)
    scene.sfx.append((0.0, "whoosh"))
    _lines(b, scene, spec, where, {int(row["b"]): i for i, row in enumerate(rows) if row["b"]})
    return scene


def _quote(b: _Builder, spec: dict, kicker: str) -> Scene:
    first, last = spec["lines"]
    where = f"{spec['file']}:{first}-{last}"
    if spec["file"].lower().endswith((".html", ".htm")):
        raise StoryboardError(f'{where}: a quote scene shows a text file as it is written, so a web page would show its '
                              'markup; use an image scene with "url" set to this file, and "find" for the words')
    paragraphs = source.excerpt(b.root, spec["file"], first, last, spec.get("ref"), spec.get("encoding"))
    size = sum(len(p) for p in paragraphs)
    if size > MAX_QUOTE_CHARS:
        raise StoryboardError(f"{where} is {size} characters of text; quote at most {MAX_QUOTE_CHARS} per scene")

    # Every marked phrase must be found, word for word, in the text that is actually on screen.
    found: list[list[tuple[int, int, int]]] = [[] for _ in paragraphs]   # per paragraph: (start, end, mark id)
    ids: dict[int, list[int]] = {}                                        # action -> its mark ids
    for act in _actions(spec):
        phrases = act.get("mark") or []
        for phrase in [phrases] if isinstance(phrases, str) else phrases:
            for p, para in enumerate(paragraphs):
                # As it appears on screen, or as copied from the raw Markdown.
                needle = next((n for n in (" ".join(phrase.split()), source.clean(phrase)) if n and n in para), None)
                at = para.find(needle) if needle else -1
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

    # Split each paragraph where a mark or a $...$ span starts or ends. A mark may hold whole math spans,
    # but may not cut one: what is highlighted must be what the reader sees.
    on = _math_on(b, spec)
    segments, lengths = [], {}
    for para, spans in zip(paragraphs, found):
        maths = texmath.spans(para) if on else []
        for s, e, mid in spans:
            for ms, me, _, _ in maths:
                if s < me and ms < e and not (s <= ms and me <= e):
                    raise StoryboardError(f"{where}: mark {para[s:e]!r} cuts the math {para[ms:me]!r}; mark the "
                                          "whole expression with its $ signs, or only text outside it")
            lengths[mid] = e - s
        cuts = sorted({0, len(para), *(x for s, e, _ in spans for x in (s, e)),
                       *(x for ms, me, _, _ in maths for x in (ms, me))})
        parts = []
        for a, z in zip(cuts, cuts[1:]):
            mark = next((mid for s, e, mid in spans if s <= a and z <= e), None)
            math = next((m for m in maths if m[0] == a and m[1] == z), None)
            if math:
                part = {"tex": math[2], "display": math[3], "raw": para[a:z]}
                b.tex.append({"where": where, "tex": math[2], "display": math[3], "seg": part, "strict": False})
            else:
                part = {"text": texmath.unescape(para[a:z]) if on else para[a:z]}
            if mark is not None:
                part["mark"] = mark
            parts.append(part)
        segments.append(parts)

    scene = b.scene("quote", kicker, {**spec, "sub": _where(spec, first, last)}, sub_is_source=True,
                    paragraphs=segments)
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
    first = min((op["t"] for op in scene.payload["ops"] if op["op"] == "reveal"), default=0.0)
    if first > LEAD + 1.0:
        b.warn(where, f"nothing is on screen for the first {first:.1f} seconds; reveal the first item when the "
                      'first sentence starts (drop its "at", or put the later reveals in "cues")')
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
    on = _math_on(b, spec)
    nodes = [{**nd, "label": b.rich(nd["label"], on, where), "desc": b.rich(nd.get("desc"), on, where)} for nd in nodes]
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
    on = _math_on(b, spec)
    columns = [{**c, "title": b.rich(c["title"], on, where), "points": [b.rich(p, on, where) for p in c["points"]]}
               for c in columns]
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
    on = _math_on(b, spec)
    items = [{**it, "label": b.rich(it.get("label"), on, where), "note": b.rich(it.get("note"), on, where)}
             for it in items]
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
    on = _math_on(b, spec)
    items = [{**it, "title": b.rich(it["title"], on, where), "detail": b.rich(it.get("detail"), on, where)}
             for it in items]
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
    for note in pic.get("notes", []):
        if note not in b.noted:                    # one page shown in several scenes: say it once
            b.noted.add(note)
            b.warn(where, note)

    def rects(value) -> list[list[float]]:
        """A region as boxes: one per line for text found on the page, one for coordinates."""
        if isinstance(value, dict):
            hit = pic["found"].get(value["find"])
            if hit is None:
                why = pic.get("why", {}).get(value["find"])
                if why in ("below", "above"):
                    raise StoryboardError(f"{where}: the text {value['find']!r} is on the page but {why} the part that was "
                                          'captured; start the capture near it with "top": "words where that part starts"')
                raise StoryboardError(f"{where}: the text {value['find']!r} is not on the page; "
                                      "it must be copied exactly from what is shown")
            pad = 0.006 if len(hit) == 1 else 0.003     # a little air around the words
            py = pad * pic["iw"] / pic["ih"]
            out = []
            for x, y, w, h in hit:
                x0, y0, x1, y1 = max(0, x - pad), max(0, y - py), min(1, x + w + pad), min(1, y + h + py)
                out.append([round(v, 5) for v in (x0, y0, x1 - x0, y1 - y0)])
            return out
        if len(value) != 4 or not all(0 <= v <= 1 for v in value):
            raise StoryboardError(f"{where}: a region is [x, y, width, height], each from 0 to 1, not {value!r}")
        return [list(value)]

    def around(boxes: list[list[float]]) -> list[float]:
        """The single rectangle that holds all of a region's boxes, for the camera to frame."""
        x0, y0 = min(b[0] for b in boxes), min(b[1] for b in boxes)
        x1, y1 = max(b[0] + b[2] for b in boxes), max(b[1] + b[3] for b in boxes)
        return [round(v, 5) for v in (x0, y0, x1 - x0, y1 - y0)]

    def framing(value) -> list[float]:
        """What the camera should hold for a zoom: the words, and on a web page the whole width of the
        paragraph they sit in, so a close-up never cuts a line of text in half."""
        x, y, w, h = around(rects(value))
        block = pic.get("blocks", {}).get(value["find"]) if isinstance(value, dict) else None
        if block:
            left, right = min(x, block[0]), max(x + w, min(1.0, block[0] + block[1]))
            x, w = left, right - left
        return [round(v, 5) for v in (x, y, w, h)]

    # What the camera shows, as the player frames it (see builders.image in player.js), to catch a box
    # drawn where nobody is looking. The frame's shape is approximate: the header's height is measured there.
    shape = (1.2 if b.fmt == "tall" else 0.4)          # frame height / width
    span = pic["ih"] / pic["iw"]                        # picture height in units of its width
    shape = min(shape, span)

    def view(region) -> list[float]:
        """[x, y, width, height] of the picture in frame, as fractions of the picture."""
        if not region:
            return [0.0, 0.0, 1.0, shape / span]
        x, y, w, h = region
        frame_px = 952 if b.fmt == "tall" else 1712
        cap = max(1.0, min(2.5, h * span * 1.08 / shape))
        width = min(cap, max(1 / 3, frame_px / 1.6 / pic["iw"], w * 1.3, h * span * 1.3 / shape))
        left = (1 - width) / 2 if width >= 1 else min(max(0.0, x + w / 2 - width / 2), 1 - width)
        tall = width * shape / span
        return [left, min(max(0.0, y + h / 2 - tall / 2), max(0.0, 1 - tall)), width, tall]

    def share_in_view(box: list[float], cam: list[float]) -> float:
        ox = max(0.0, min(box[0] + box[2], cam[0] + cam[2]) - max(box[0], cam[0]))
        oy = max(0.0, min(box[1] + box[3], cam[1] + cam[3]) - max(box[1], cam[1]))
        return ox * oy / max(box[2] * box[3], 1e-9)

    camera = view(None)
    views: list[list[float]] = []                       # every framing this scene uses
    boxes: list[list[list[float]]] = []
    scene = b.scene("image", kicker, {**spec, "sub": spec.get("sub") or pic["label"]}, sub_is_source=not spec.get("sub"),
                    src=pic["path"].as_uri(), iw=pic["iw"], ih=pic["ih"], stamp=pic["stamp"], boxes=boxes)
    ops = scene.payload["ops"]
    scene.sfx.append((0.0, "whoosh"))
    clock = _Clock(b, scene, where)
    for n, beat in enumerate(spec.get("beats", [])):
        for t, act, src in clock.beat(beat):
            if n == 0 and src is beat and "zoom" not in act:
                views.append(camera)                    # the scene opens on the top of the picture
            if "zoom" in act:
                ops.append({"op": "cam", "t": t, "region": framing(act["zoom"]) if act["zoom"] else None})
                scene.sfx.append((t, "zoom"))
                camera = view(ops[-1]["region"])
                views.append(camera)
            if "box" in act:
                if act["box"]:
                    boxes.append(rects(act["box"]))
                    if share_in_view(around(boxes[-1]), camera) < 0.6:
                        name = act["box"]["find"] if isinstance(act["box"], dict) else act["box"]
                        b.warn(where, f"the box on {name!r} is outside what the camera shows at that moment; "
                                      'add "zoom" to the same region on that beat')
                    ops.append({"op": "box", "t": round(t + (0.5 if "zoom" in act else 0.0), 3), "id": len(boxes) - 1})
                    scene.sfx.append((ops[-1]["t"], "tick"))
                else:
                    ops.append({"op": "box", "t": t, "id": -1})
    seen = [thing for thing in pic.get("avoid", []) if any(share_in_view(thing["rect"], cam) > 0.15 for cam in views)]
    for what in sorted({thing["what"] for thing in seen}):
        count = sum(1 for thing in seen if thing["what"] == what)
        fix = next(thing["fix"] for thing in seen if thing["what"] == what)
        b.warn(where, f"in frame during this scene: {what}{f', {count} times' if count > 1 else ''}; {fix}")
    clock.finish()
    return scene


def _notes(scene: Scene, clock: _Clock, beat: dict, state: dict) -> None:
    """A note belongs to its sentence: a new sentence with no note takes the last one down."""
    if state.get("noted") and not beat.get("note"):
        scene.payload["ops"].append({"op": "note", "t": clock.started, "text": None})
        state["noted"] = False


def _math(b: _Builder, spec: dict, kicker: str) -> Scene:
    where = spec.get("heading") or "math"
    if spec.get("file"):
        first, last = spec["lines"]
        where = f"{spec['file']}:{first}-{last}"
        blocks, first_line = source.display_math(b.root, spec["file"], first, last, spec.get("ref"), spec.get("encoding"))
        if spec.get("expect") and spec["expect"] not in first_line:
            raise StoryboardError(f"{where}: line {first} is {first_line.strip()[:60]!r}, not the expected "
                                  f"{spec['expect']!r}; the file has changed, so fix the line range")
        sub, from_source = _where(spec, first, last), True
    elif spec.get("tex"):
        blocks = [spec["tex"]] if isinstance(spec["tex"], str) else list(spec["tex"])
        sub, from_source = spec.get("sub"), False
    else:
        raise StoryboardError(f'{where}: a math scene needs "tex" (formulas written for the video) or "file" and '
                              '"lines" (formulas from the source)')
    if not 1 <= len(blocks) <= MAX_MATH_LINES:
        raise StoryboardError(f"{where}: a math scene shows 1 to {MAX_MATH_LINES} formulas, not {len(blocks)}; "
                              "split it into two scenes")

    # Marks: a piece of one formula's LaTeX, wrapped in \htmlClass so the player can highlight it.
    spans: dict[int, list[tuple[int, int, int]]] = {i: [] for i in range(len(blocks))}
    ids: dict[int, list[tuple[int, int]]] = {}
    for act in _actions(spec):
        value = act.get("mark")
        if not value:
            continue
        for item in [value] if isinstance(value, dict) else value:
            line, piece = int(item.get("line", 1)), item.get("tex", "")
            if not 1 <= line <= len(blocks):
                raise StoryboardError(f"{where}: mark line {line} is not one of the {len(blocks)} formulas")
            at = blocks[line - 1].find(piece) if piece else -1
            if at < 0:
                raise StoryboardError(f"{where}: mark {piece!r} is not in formula {line}; copy it exactly from the LaTeX")
            if not texmath.balanced(piece):
                raise StoryboardError(f"{where}: mark {piece!r} is not a whole piece of LaTeX (its braces do not pair "
                                      "up); mark a complete term")
            if any(s < at + len(piece) and at < e for s, e, _ in spans[line - 1]):
                raise StoryboardError(f"{where}: mark {piece!r} overlaps an earlier mark")
            mid = sum(len(v) for v in spans.values())
            spans[line - 1].append((at, at + len(piece), mid))
            ids.setdefault(id(act), []).append((mid, line - 1))
    shown = []
    for i, tex in enumerate(blocks):
        for s, e, mid in sorted(spans[i], reverse=True):
            tex = f"{tex[:s]}\\htmlClass{{idr-m{mid}}}{{{tex[s:e]}}}{tex[e:]}"
        shown.append(tex)
        b.tex.append({"where": f"{where} formula {i + 1}", "tex": tex, "display": True, "seg": None, "strict": True})

    scene = b.scene("math", kicker, {**spec, "sub": sub}, sub_is_source=from_source, blocks=shown, source=from_source)
    scene.sfx.append((0.0, "whoosh"))
    ops = scene.payload["ops"]
    clock = _Clock(b, scene, where)
    stage = _Stage(scene, len(blocks), "line", _staged(spec))
    state, last_mark = {}, None
    for beat in spec.get("beats", []):
        timed = clock.beat(beat)
        _notes(scene, clock, beat, state)
        for t, act, src in timed:
            if "reveal" in act:
                stage.upto(act["reveal"], t)
            if "mark" in act and act["mark"] is None:
                ops.append({"op": "mark", "t": t, "id": None})
                last_mark = None
            for j, (mid, line) in enumerate(ids.get(id(src), [])):
                if line >= stage.visible:
                    b.warn(where, f"a mark is on formula {line + 1} before it is revealed")
                at = round(t + 0.1 + j * 0.45, 3)
                ops.append({"op": "mark", "t": at, "id": mid})
                scene.sfx.append((at, "mark"))
                last_mark = mid
            if act.get("note"):
                ops.append({"op": "note", "t": round(t + 0.15, 3), "text": act["note"], "id": last_mark})
                state["noted"] = True
    stage.upto(len(blocks), clock.t)
    clock.finish()
    return scene


def _numeric(cell: str) -> bool:
    return bool(re.fullmatch(r"[-+−~≈]?[\d][\d,]*(\.\d+)?\s*(%|x|×|ms|s|MB|KB|GB|bpc|bits?)?", cell.strip()))


def _table(b: _Builder, spec: dict, kicker: str) -> Scene:
    where = spec.get("heading") or "table"
    aligns, credit, from_source = None, None, True
    if spec.get("file"):
        name = spec["file"]
        at_ref = f"  ·  as of {spec['ref']}" if spec.get("ref") else ""
        if name.lower().endswith((".csv", ".tsv")):
            if "rows" not in spec:
                raise StoryboardError(f'{name}: a CSV table takes "rows": [first, last] (data rows, after the header)')
            first, last = spec["rows"]
            where = f"{name} rows {first}-{last}"
            header, rows = source.csv_table(b.root, name, first, last, spec.get("columns"), spec.get("ref"),
                                            spec.get("encoding"))
            if spec.get("expect") and spec["expect"] not in ",".join(header):
                raise StoryboardError(f"{where}: the header is {', '.join(header)!r}, not the expected {spec['expect']!r}")
            sub = f"{name}  ·  {f'row {first}' if first == last else f'rows {first}–{last}'}{at_ref}"
        else:
            first, last = spec["lines"]
            where = f"{name}:{first}-{last}"
            header, aligns, rows, first_line = source.md_table(b.root, name, first, last, spec.get("ref"),
                                                               spec.get("encoding"))
            if spec.get("expect") and spec["expect"] not in first_line:
                raise StoryboardError(f"{where}: line {first} is {first_line.strip()[:60]!r}, not the expected "
                                      f"{spec['expect']!r}; the file has changed, so fix the line range")
            sub = _where(spec, first, last)
    elif "header" in spec and "rows" in spec:
        header, rows = [str(h) for h in spec["header"]], [[str(c) for c in row] for row in spec["rows"]]
        for n, row in enumerate(rows, 1):
            if len(row) != len(header):
                raise StoryboardError(f"{where}: row {n} has {len(row)} cells but the header has {len(header)}")
        sub, credit, from_source = spec.get("sub"), spec.get("source"), False
    else:
        raise StoryboardError(f'{where}: a table scene needs "header" and "rows" (a table written for the video), '
                              'or "file" with "lines" (a Markdown table) or "rows" (a CSV file)')
    if not 1 <= len(header) <= MAX_TABLE_COLS:
        raise StoryboardError(f"{where}: a table shows 1 to {MAX_TABLE_COLS} columns, not {len(header)}")
    if not 1 <= len(rows) <= MAX_TABLE_ROWS:
        raise StoryboardError(f"{where}: a table shows 1 to {MAX_TABLE_ROWS} rows, not {len(rows)}; split it")
    if b.fmt == "tall" and len(header) > 4:
        b.warn(where, f"{len(header)} columns are cramped in the tall format; show 4 or fewer")
    for cell in [*header, *(c for row in rows for c in row)]:
        if len(cell) > MAX_CELL_CHARS:
            b.warn(where, f"cell {cell[:30]!r}... is over {MAX_CELL_CHARS} characters")
    if not aligns or not any(aligns):
        aligns = ["right" if any(r[c].strip() for r in rows) and all(_numeric(r[c]) for r in rows if r[c].strip())
                  else None for c in range(len(header))]

    on = _math_on(b, spec)
    scene = b.scene("table", kicker, {**spec, "sub": sub}, sub_is_source=from_source,
                    header=[b.rich(h, on, where) for h in header],
                    rows=[[b.rich(c, on, where) for c in row] for row in rows],
                    aligns=aligns, credit=b.rich(credit, on, where), source=from_source)
    scene.sfx.append((0.0, "whoosh"))
    ops = scene.payload["ops"]

    def column(value) -> int:
        if isinstance(value, int):
            if not 1 <= value <= len(header):
                raise StoryboardError(f"{where}: there is no column {value}; the table has {len(header)}")
            return value - 1
        if value in header:
            return header.index(value)
        raise StoryboardError(f"{where}: there is no column {value!r}; the columns are {', '.join(header)}")

    def row(value) -> int:
        if not isinstance(value, int) or not 1 <= value <= len(rows):
            raise StoryboardError(f"{where}: there is no row {value!r}; the table has {len(rows)} data rows")
        return value - 1

    clock = _Clock(b, scene, where)
    stage = _Stage(scene, len(rows), "row", _staged(spec))
    state, current = {}, None
    for beat in spec.get("beats", []):
        timed = clock.beat(beat)
        _notes(scene, clock, beat, state)
        for t, act, _ in timed:
            if "reveal" in act:
                stage.upto(act["reveal"], t)
            if "highlight" in act:
                value = act["highlight"]
                if value is None:
                    target = None
                elif "cell" in value:
                    target = (row(value["cell"][0]), column(value["cell"][1]))
                elif "row" in value:
                    target = (row(value["row"]), None)
                elif "col" in value:
                    target = (None, column(value["col"]))
                else:
                    raise StoryboardError(f'{where}: highlight is {{"row": n}}, {{"col": name}} or {{"cell": [n, name]}}')
                if target and target[0] is not None and target[0] >= stage.visible:
                    b.warn(where, f"row {target[0] + 1} is highlighted before it is revealed")
                if target != current:
                    ops.append({"op": "hl", "t": t, "row": target[0] if target else None,
                                "col": target[1] if target else None, "on": target is not None})
                    if target:
                        scene.sfx.append((t, "tick"))
                    current = target
            if act.get("note") and current:
                ops.append({"op": "note", "t": round(t + 0.1, 3), "text": act["note"]})
                state["noted"] = True
    stage.upto(len(rows), clock.t)
    clock.finish()
    return scene


def _overview(b: _Builder, title: str, chapters: list[dict], intro: dict) -> Scene:
    """Opening card that lists the chapters, so the outline is watched instead of read."""
    on = b.math_default
    scene = b.scene("steps", "In this video", {"heading": title},
                    items=[{"title": b.rich(c["title"], on, title)} for c in chapters])
    scene.sfx.append((0.12, "chime"))
    for j in range(len(chapters)):
        scene.payload["ops"].append({"op": "reveal", "t": round(0.6 + j * 0.22, 3), "item": j})
    clock = _Clock(b, scene, title, 0.75)
    if intro.get("say"):
        clock.beat({"say": intro["say"], "speak": intro.get("speak")})
    clock.finish(minimum=2.6 + 0.35 * len(chapters))
    return scene


def _check_math(b: _Builder) -> list[str]:
    """Render every expression once with KaTeX. A formula scene that fails is an error; inline math that fails
    is shown as the plain text it is in the source (so the screen still shows only what is there) and warned about."""
    if not b.tex:
        return []
    errors = texmath.validate([(x["tex"], x["display"]) for x in b.tex])
    if errors is None:
        b.warn("math", "no browser could be started to check the LaTeX; mistakes will show as red text")
        return []
    problems = []
    for item, error in zip(b.tex, errors):
        if not error:
            continue
        if item["strict"]:
            problems.append(f"{item['where']}: LaTeX error: {error}")
        else:
            b.warn(item["where"], f"{item['seg']['raw']!r} is not valid LaTeX ({error}); it is shown as plain text")
            seg = item["seg"]
            kept = {"text": seg["raw"], **({"mark": seg["mark"]} if "mark" in seg else {})}
            seg.clear()
            seg.update(kept)
    return problems


def _plot(b: _Builder, spec: dict, kicker: str) -> Scene:
    """The graph of one to three functions of x, with points, tangents and shaded areas computed from them."""
    where = spec.get("heading") or "plot"
    given = spec.get("curves") or ([{"expr": spec["expr"], "name": spec.get("name")}] if spec.get("expr") else [])
    given = [{"expr": c} if isinstance(c, str) else c for c in given]
    if not 1 <= len(given) <= MAX_CURVES:
        raise StoryboardError(f'{where}: a plot scene draws 1 to {MAX_CURVES} curves ("expr", or "curves": [...]), '
                              f"not {len(given)}")
    x = spec.get("x")
    if not (isinstance(x, list) and len(x) == 2 and all(isinstance(v, (int, float)) for v in x) and x[0] < x[1]):
        raise StoryboardError(f'{where}: a plot scene needs "x": [from, to], two numbers with the smaller first')
    x0, x1 = float(x[0]), float(x[1])
    try:
        formulas = [plot.Formula(c.get("expr")) for c in given]
        if spec.get("y"):
            y0, y1 = (float(v) for v in spec["y"])
            if not y0 < y1:
                raise ValueError('"y": [from, to] needs the smaller number first')
        else:
            y0, y1 = plot.view(formulas, x0, x1)
    except ValueError as problem:
        raise StoryboardError(f"{where}: {problem}") from None

    curves = []
    for n, (c, f) in enumerate(zip(given, formulas), 1):
        name = c.get("name")
        if name is not None and not re.fullmatch(r"[A-Za-z]", name):
            raise StoryboardError(f'{where}: a curve\'s "name" is one letter, as in f for f(x); not {name!r}')
        lines = plot.strokes(f, x0, x1, y0, y1)
        if not any(y0 <= py <= y1 for line in lines for _, py in line):
            raise StoryboardError(f"{where}: {f.text!r} is never inside the graph for x from {plot.number(x0)} to "
                                  f'{plot.number(x1)}; change "x" or "y"')
        label = f"{name}(x) = {f.tex()}" if name else f"y = {f.tex()}"
        b.tex.append({"where": f"{where} curve {n}", "tex": label, "display": False, "seg": None, "strict": True})
        curves.append({"tex": label, "lines": lines})

    def curve(value: dict, what: str) -> int:
        on = value.get("on", 1)
        if not isinstance(on, int) or not 1 <= on <= len(curves):
            raise StoryboardError(f'{where}: {what} is "on" curve {on!r}, but the scene has {len(curves)}')
        return on - 1

    def inside(i: int, at: float, what: str) -> float:
        if not x0 <= at <= x1:
            raise StoryboardError(f"{where}: {what} at x = {plot.number(at)} is outside the graph "
                                  f"({plot.number(x0)} to {plot.number(x1)})")
        value = formulas[i](at)
        if value != value:
            raise StoryboardError(f"{where}: {formulas[i].text!r} has no value at x = {plot.number(at)}")
        if not y0 <= value <= y1:
            raise StoryboardError(f"{where}: {what} at x = {plot.number(at)} is at y = {plot.number(value)}, outside "
                                  f'the graph ({plot.number(y0)} to {plot.number(y1)}); set "y" to include it')
        return float(value)

    marks: list[dict] = []
    owner: dict[int, list[tuple[str, int]]] = {}

    def label(tex: str, what: str) -> str:
        b.tex.append({"where": f"{where} {what}", "tex": tex, "display": False, "seg": None, "strict": True})
        return tex

    # Everything drawn on a curve is worked out from its formula here, never typed into the storyboard.
    for act in _actions(spec):
        for kind in ("point", "tangent", "shade"):
            value = act.get(kind)
            if not value:
                continue
            for item in [value] if isinstance(value, dict) else value:
                if not isinstance(item, dict):
                    raise StoryboardError(f'{where}: "{kind}" takes an object such as {{"x": 1}}, or a list of them')
                i = curve(item, f"a {kind}")
                f = formulas[i]
                if kind == "shade":
                    if not all(isinstance(item.get(k), (int, float)) for k in ("from", "to")) or item["from"] >= item["to"]:
                        raise StoryboardError(f'{where}: "shade" needs "from" and "to", two x values, smaller first')
                    lo, hi = float(item["from"]), float(item["to"])
                    inside(i, lo, "the shaded area"), inside(i, hi, "the shaded area")
                    area = f.area(lo, hi)
                    if area != area:
                        raise StoryboardError(f"{where}: {f.text!r} has no value somewhere between x = "
                                              f"{plot.number(lo)} and {plot.number(hi)}, so there is no area to shade")
                    xs = [lo + (hi - lo) * k / 160 for k in range(161)]
                    ys = [min(max(v, y0), y1) for v in f(xs).tolist()]
                    sign = r"\approx" if plot.rounded(area) else "="
                    marks.append({"kind": "shade", "curve": i, "outline": [[round(a, 6), round(v, 6)] for a, v in zip(xs, ys)],
                                  "tex": label(rf"\text{{area}} {sign} {plot.number(area)}", "area")})
                else:
                    if not isinstance(item.get("x"), (int, float)):
                        raise StoryboardError(f'{where}: "{kind}" needs "x", the place on the curve')
                    at = float(item["x"])
                    value_y = inside(i, at, f"the {kind}")
                    if kind == "point":
                        marks.append({"kind": "point", "curve": i, "x": at, "y": value_y,
                                      "tex": label(rf"\left({plot.number(at)},\ {plot.number(value_y)}\right)", "point")})
                    else:
                        slope = f.slope(at, x1 - x0)
                        if slope != slope:
                            raise StoryboardError(f"{where}: {f.text!r} has no slope at x = {plot.number(at)}")
                        sign = r"\approx" if plot.rounded(slope) else "="
                        marks.append({"kind": "tangent", "curve": i, "x": at, "y": value_y, "slope": slope,
                                      "tex": label(rf"\text{{slope}} {sign} {plot.number(slope)}", "slope")})
                owner.setdefault(id(act), []).append((kind, len(marks) - 1))

    on = _math_on(b, spec)
    scene = b.scene("plot", kicker, spec, x=[x0, x1], y=[y0, y1], curves=curves, marks=marks,
                    xticks=[[v, plot.minus(plot.number(v))] for v in plot.ticks(x0, x1, 10 if b.fmt == "wide" else 6)],
                    yticks=[[v, plot.minus(plot.number(v))] for v in plot.ticks(y0, y1, 7 if b.fmt == "wide" else 9)],
                    xlabel=spec.get("xlabel", "x"), ylabel=spec.get("ylabel", "y"),
                    credit=b.rich(spec.get("source"), on, where))
    scene.sfx.append((0.0, "whoosh"))
    ops = scene.payload["ops"]
    clock = _Clock(b, scene, where)
    stage = _Stage(scene, len(curves), "curve", _staged(spec))
    shown: dict[str, list[int]] = {"point": [], "tangent": [], "shade": []}
    for beat in spec.get("beats", []):
        for t, act, src in clock.beat(beat):
            if "reveal" in act:
                stage.upto(act["reveal"], t)
            for kind in shown:
                if kind not in act:
                    continue
                for mid in shown[kind]:                # a new point, tangent or area replaces the ones of its kind
                    ops.append({"op": "hide", "t": t, "mark": mid})
                shown[kind] = [mid for k, mid in owner.get(id(src), []) if k == kind]
                for j, mid in enumerate(shown[kind]):
                    if marks[mid]["curve"] >= stage.visible:
                        b.warn(where, f"a {kind} is on curve {marks[mid]['curve'] + 1} before that curve is revealed")
                    at = round(t + 0.12 + j * 0.3, 3)
                    ops.append({"op": "show", "t": at, "mark": mid})
                    scene.sfx.append((at, "mark" if kind == "shade" else "tick"))
    stage.upto(len(curves), clock.t)
    first = min((op["t"] for op in ops if op["op"] == "reveal"), default=0.0)
    if first > LEAD + 1.0:
        b.warn(where, f"the graph is empty for the first {first:.1f} seconds; draw the first curve when the first "
                      "sentence starts")
    clock.finish()
    return scene


SCENES = {"code": _code, "diff": _diff, "quote": _quote, "image": _image, "flow": _flow, "compare": _compare,
          "stats": _stats, "steps": _steps, "math": _math, "table": _table, "plot": _plot}
OVERVIEW_FROM = 3   # videos with this many chapters open with a card that lists them


def build(storyboard: dict, root: Path, theme: str, narrator, captions: bool = True,
          fmt: str = "wide") -> tuple[list[Scene], list[str]]:
    """All scenes of the video in order, plus warnings about things that may not read well."""
    b = _Builder(root, theme, narrator, captions, fmt)
    b.math_default = bool(storyboard.get("math", True))
    scenes: list[Scene] = []
    problems: list[str] = []
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
                problems.append(f"chapter {n}, {spec['type']} scene: missing field {missing}")
            except (ValueError, FileNotFoundError) as problem:      # report every scene's problem in one run
                problems.append(str(problem))
    problems += _check_math(b)
    if problems:
        raise StoryboardError("\nerror: ".join(problems))
    scenes[0].payload["opening"] = True               # drawn in full from the first frame (see player.js)
    return scenes, b.warnings
