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

from . import picture, plot, source, speech, texmath

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

_NOT_ACTIONS = {"say", "speak", "hold", "cues", "at"}
# What a beat or a cue may do in each kind of scene. Anything else is a slip of the hand (a misspelt field, or
# one that belongs to another scene), and it would otherwise be dropped without a word.
BEAT_ACTIONS = {"code": {"highlight", "note"}, "diff": {"highlight", "note", "show"}, "quote": {"mark"},
                "image": {"zoom", "box"}, "flow": {"reveal", "focus"}, "compare": {"reveal"}, "stats": {"reveal"},
                "steps": {"reveal"}, "math": {"reveal", "mark", "note"}, "table": {"reveal", "highlight", "note"},
                "plot": {"reveal", "point", "tangent", "secant", "shade", "riemann", "arrow", "move", "stage", "sweep"},
                "diagram": {"reveal", "focus", "follow"}, "array": {"do", "mark", "pointers"},
                "sequence": {"reveal", "focus"}, "chart": {"reveal", "highlight"}}


def _only(given, allowed, what: str, where: str) -> None:
    """Stop on a field that `what` does not take, naming the nearest one it does."""
    import difflib
    for key in given:
        if key not in allowed:
            near = difflib.get_close_matches(str(key), sorted(allowed), 1)
            raise StoryboardError(f'{where}: "{key}" is not a field of {what}'
                                  + (f'; did you mean "{near[0]}"?' if near else ".")
                                  + f" It takes: {', '.join(sorted(allowed))}")


def _check_beats(spec: dict, where: str) -> None:
    kind = spec.get("type")
    allowed = BEAT_ACTIONS.get(kind)
    if allowed is None:
        return
    for beat in spec.get("beats") or []:
        if not isinstance(beat, dict):
            raise StoryboardError(f"{where}: a beat is an object such as {{\"say\": \"One sentence.\"}}, not {beat!r}")
        _only(beat, allowed | _NOT_ACTIONS, f"a beat in a {kind} scene", where)
        for cue in beat.get("cues") or []:
            if not isinstance(cue, dict):
                raise StoryboardError(f'{where}: a cue is an object such as {{"at": "a word", ...}}, not {cue!r}')
            _only(cue, allowed | {"at"}, f"a cue in a {kind} scene", where)
EXAMPLE_SUB = "Example written for this video"


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
    starts: list[float] = field(default_factory=list)  # when each beat (each sentence) begins

    @property
    def frames(self) -> int:
        return round(self.duration * FPS)


@dataclass
class _DryClip:
    samples: np.ndarray
    duration: float
    words: list = field(default_factory=list)


class DryNarrator:
    """Stands in for the voice when only checking a storyboard: makes no sound. A sentence that has been
    spoken before on this machine keeps its real length and word timings; any other is estimated."""

    voice, speed, guessed = "af_heart", 1.0, 0

    def __init__(self, voice: str = "af_heart", speed: float = 1.0):
        self.voice, self.speed, self.guessed = voice, float(speed or 1.0), 0

    def estimate(self, text: str) -> float:
        """Fitted to the voice on a few hundred sentences. Letters alone run 10% short on a sentence full of
        numbers: the voice says every digit ("six point one four three") and stops at every comma."""
        letters, digits = sum(c.isalpha() for c in text), sum(c.isdigit() for c in text)
        points = len(re.findall(r"(?<=\d)\.(?=\d)", text))
        pauses, stops = len(re.findall(r"[,;:—]", text)), len(re.findall(r"[.!?](?=\s|$)", text))
        seconds = 0.0564 * letters + 0.4 * digits + 0.3 * points + 0.076 * len(text.split()) + 0.15 * pauses \
            + 0.335 * stops - 0.66
        return max(0.6, len(text) / 20, seconds) / self.speed

    def say(self, text: str) -> _DryClip:
        known = None
        try:
            from .tts import remembered
            known = remembered(text, self.voice, self.speed)
        except Exception:                                  # no audio library here: every sentence is an estimate
            pass
        if known:
            return _DryClip(np.zeros(int(known[0] * 24000), dtype=np.float32), known[0], known[1])
        self.guessed += 1
        dur = self.estimate(text)
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
        self.pronounce: dict[str, str] = {}   # written word -> how the voice should say it, for every sentence
        self.home = root                      # the storyboard's own folder: where an example written for the video is
        self.tex: list[dict] = []      # every LaTeX expression on screen, checked with KaTeX once all scenes are built
        self.macros = texmath.Macros() # the commands of the LaTeX file the scene being built reads from

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
            seg = {"tex": texmath.expand(tex, self.macros.optional), "display": display, "raw": value[start:end]}
            self.tex.append({"where": where, "tex": seg["tex"], "display": display, "seg": seg, "strict": False,
                             "macros": self.macros})
            segs.append(seg)
            pos = end
        if pos < len(value):
            segs.append({"text": texmath.unescape(value[pos:])})
        return segs

    def warn(self, where: str, message: str) -> None:
        self.warnings.append(f"{where}: {message}")

    def note(self, where: str, message: str) -> None:
        """Something the author should know and need not change: how an ambiguous thing was read, and how to say otherwise."""
        self.warnings.append(f"note: {where}: {message}")

    def scene(self, kind: str, kicker, spec: dict, sub_is_source: bool = False, **extra) -> Scene:
        heading = spec.get("heading")
        if heading and len(heading) > 60:
            self.warn(heading[:30] + "...", "heading is over 60 characters and may wrap badly")
        on, where = _math_on(self, spec), heading or kind
        sub = spec.get("sub") if sub_is_source else self.rich(spec.get("sub"), on, where)
        return Scene({"type": kind, "theme": self.theme, "format": self.fmt, "kicker": kicker,
                      "heading": self.rich(heading, on, where), "sub": sub, "ops": [],
                      **({"macros": dict(self.macros)} if self.macros else {}), **extra})


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
        self.scene.starts.append(self.started)
        exact = not beat.get("speak")
        if text:
            if len(text) > MAX_SAY_CHARS:
                self.b.warn(self.where, f"a sentence is {len(text)} characters; split it into two beats")
            problem = speech.trouble(beat.get("speak") or text, self.b.pronounce)
            if problem:                                 # after notation has been turned into words (speech.py)
                self.b.warn(self.where, f"in the sentence {text[:44]!r}..., {problem}; "
                            + ('write "speak" in plain words' if beat.get("speak") else
                               'add "speak" with how it should be said aloud') + " (guides/voice.md has the rules)")
            clip = self.b.narrator.say(speech.spoken(beat.get("speak") or text, self.b.pronounce))
            self.scene.narration.append((start, clip.samples))
            self._captions(text, start, clip, exact)
            self.t = start + clip.duration + GAP
        else:
            hold = beat.get("hold", HOLD)
            if isinstance(hold, bool) or not isinstance(hold, (int, float)) or not 0 <= hold <= 60:
                raise StoryboardError(f'{self.where}: "hold" is how many seconds a beat with no sentence lasts, '
                                      f"a number from 0 to 60; not {hold!r}")
            self.t = start + float(hold)

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
        if isinstance(n, bool) or not isinstance(n, int) or not 0 <= n <= self.count:
            things = self.key if self.key.endswith("s") else f"{self.key}s"
            raise ValueError(f'"reveal" is how many of the {self.count} {things} are visible from then on: a whole '
                             f"number from 0 to {self.count}, not {n!r}")
        if n < self.visible:
            raise ValueError(f'"reveal": {n} comes after "reveal": {self.visible}; it says how many are visible from '
                             "then on and cannot hide one again, so the numbers only go up")
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
                    if noted and not act.get("note"):   # the note was about the lines the highlight has just left
                        ops.append({"op": "note", "t": t, "text": None})
                        noted = False
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
    if spec.get("example") and spec.get("ref"):
        raise StoryboardError(f'{where}: an example is a file you wrote for the video, so it has no "ref"')
    # An example is read from beside the storyboard, not from the source folder, which is the user's and is not written to.
    rows = source.extract(b.home if spec.get("example") else b.root, spec["file"], first, last, spec.get("ref"),
                          spec.get("encoding"))
    _expect(spec, rows, where)
    _check_rows(b, rows, where)
    # An example is code written for the video: the line under the heading says so instead of naming a file,
    # so it cannot be taken for part of the source.
    sub = EXAMPLE_SUB if spec.get("example") else _where(spec, first, last)
    scene = b.scene("code", kicker, {**spec, "sub": sub}, sub_is_source=True, rows=rows)
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
    b.macros = source.tex_macros(b.root, spec["file"], spec.get("ref"), spec.get("encoding"))
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
                part = {"tex": texmath.expand(math[2], b.macros.optional), "display": math[3], "raw": para[a:z]}
                b.tex.append({"where": where, "tex": part["tex"], "display": math[3], "seg": part, "strict": False,
                              "macros": b.macros})
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


def _in_command(tex: str, at: int) -> str | None:
    """The command name that position `at` falls inside (the "a" of \\frac), or None."""
    start = at
    while start > 0 and tex[start - 1].isalpha():
        start -= 1
    slashes = 0
    while start - slashes > 0 and tex[start - slashes - 1] == "\\":
        slashes += 1
    if slashes % 2 == 0:                                   # none, or a row break (\\\\) followed by ordinary letters
        return None
    end = at
    while end < len(tex) and tex[end].isalpha():
        end += 1
    return tex[start - 1:end] if end > start else None


def _term_spots(tex: str, piece: str) -> tuple[list[int], str | None]:
    """Where a piece of LaTeX occurs as a term of its own: not starting or ending in the middle of a command
    name. Returns the positions, and a command one of the rejected matches was inside (for the error)."""
    spots, inside, at = [], None, tex.find(piece)
    while at >= 0:
        end = at + len(piece)
        cut = (_in_command(tex, at) if piece[0].isalpha() else None) or \
              (_in_command(tex, end) if piece[-1].isalpha() and end < len(tex) and tex[end].isalpha() else None)
        if cut:
            inside = inside or cut
        else:
            spots.append(at)
        at = tex.find(piece, at + 1)
    return spots, inside


def _top_level(tex: str, tokens: tuple[str, ...]) -> bool:
    """Whether any of the tokens appears outside every pair of braces."""
    depth, i = 0, 0
    while i < len(tex):
        if tex[i] == "\\" and i + 1 < len(tex):
            if depth == 0 and tex[i:i + 2] in tokens:
                return True
            i += 2
            continue
        depth += tex[i] == "{"
        depth -= tex[i] == "}"
        if depth == 0 and tex[i] in tokens:
            return True
        i += 1
    return False


def _math(b: _Builder, spec: dict, kicker: str) -> Scene:
    where = spec.get("heading") or "math"
    if spec.get("file"):
        first, last = spec["lines"]
        where = f"{spec['file']}:{first}-{last}"
        own = source.tex_macros(b.root, spec["file"], spec.get("ref"), spec.get("encoding"))   # the paper's \newcommands
        blocks, first_line, numbers = source.display_math(b.root, spec["file"], first, last, spec.get("ref"),
                                                          spec.get("encoding"), own)
        if spec.get("expect") and spec["expect"] not in first_line:
            raise StoryboardError(f"{where}: line {first} is {first_line.strip()[:60]!r}, not the expected "
                                  f"{spec['expect']!r}; the file has changed, so fix the line range")
        sub, from_source = _where(spec, first, last), True
    elif spec.get("tex"):
        blocks = [spec["tex"]] if isinstance(spec["tex"], str) else list(spec["tex"])
        sub, from_source, own, numbers = spec.get("sub"), False, texmath.Macros(), []
    else:
        raise StoryboardError(f'{where}: a math scene needs "tex" (formulas written for the video) or "file" and '
                              '"lines" (formulas from the source)')
    if not 1 <= len(blocks) <= MAX_MATH_LINES:
        raise StoryboardError(f"{where}: a math scene shows 1 to {MAX_MATH_LINES} formulas, not {len(blocks)}; "
                              "split it into two scenes")
    for n, block in enumerate(blocks, 1):
        if not isinstance(block, str) or not block.strip():
            raise StoryboardError(f'{where}: formula {n} is {block!r}; each formula is a string of LaTeX, such as "a^2 + b^2 = c^2"')
        if not from_source:
            bare = re.sub(r"\\(?:text|mathrm|operatorname\*?|textbf|textit|mathit|mathbf|mbox|begin|end)\s*\{[^{}]*\}|\\[A-Za-z]+", " ", block)
            word = re.search(r"(?<![A-Za-z])[A-Za-z]{5,}(?![A-Za-z])", bare)
            if word:                                       # five letters in a row are a word, not a product of five quantities
                b.warn(where, f"formula {n} has the word {word.group(0)!r} written as math, so it is set as a row of "
                              f"letters with no spaces; put words in \\text{{...}}, or say them in the narration")

    # Marks: a piece of one formula's LaTeX, wrapped in \htmlClass so the player can highlight it.
    spans: dict[int, list[tuple[int, int, int]]] = {i: [] for i in range(len(blocks))}
    ids: dict[int, list[tuple[int, int]]] = {}
    for act in _actions(spec):
        value = act.get("mark")
        if not value:
            continue
        if not isinstance(value, (dict, list)):
            raise StoryboardError(f'{where}: "mark" takes {{"line": 1, "tex": "a piece of that formula"}}, or a list of '
                                  f'them (null clears the marks); not {value!r}')
        for item in [value] if isinstance(value, dict) else value:
            if not isinstance(item, dict) or not isinstance(item.get("tex"), str) or not item["tex"].strip():
                raise StoryboardError(f'{where}: a mark is {{"line": 1, "tex": "a piece of that formula"}}; not {item!r}')
            line, piece, nth = item.get("line", 1), item["tex"], item.get("nth", 1)
            if isinstance(line, bool) or not isinstance(line, int) or not 1 <= line <= len(blocks):
                raise StoryboardError(f"{where}: mark line {line!r} is not one of the {len(blocks)} formulas")
            if isinstance(nth, bool) or not isinstance(nth, int) or nth < 1:
                raise StoryboardError(f'{where}: a mark\'s "nth" is 1 for the first place the piece occurs, 2 for the second')
            block = blocks[line - 1]
            if piece not in block:
                raise StoryboardError(f"{where}: mark {piece} is not in formula {line}; copy it exactly from the LaTeX"
                                      + (" of the file, written with the paper's own commands" if from_source else ""))
            if not texmath.balanced(piece):
                raise StoryboardError(f"{where}: mark {piece!r} is not a whole piece of LaTeX (its braces do not pair "
                                      "up); mark a complete term")
            if _top_level(piece, ("&", "\\\\")):
                raise StoryboardError(f"{where}: mark {piece!r} runs across rows or columns (it has & or \\\\ in it), "
                                      "which would change the formula; mark the part in one cell")
            spots, inside = _term_spots(block, piece)
            if not spots:
                raise StoryboardError(f"{where}: mark {piece!r} is only found inside the command {inside} in formula "
                                      f"{line}, not as a term of its own; mark a longer piece that contains it")
            if nth > len(spots):
                raise StoryboardError(f"{where}: mark {piece!r} occurs {len(spots)} time(s) in formula {line}, so there "
                                      f'is no "nth": {nth}')
            at = spots[nth - 1]
            if block[:at].rstrip().endswith(("^", "_")):
                whole_group = piece.startswith("{") and texmath.balanced(piece[1:-1]) and piece.endswith("}") \
                    and not _top_level(piece[1:-1] + "}", ("}",))
                if not (len(piece) == 1 or whole_group or re.fullmatch(r"\\[A-Za-z]+", piece)):
                    raise StoryboardError(f"{where}: mark {piece!r} starts in an exponent or subscript and runs past "
                                          "it; mark the whole exponent or subscript, or a term outside it")
            same = next((mid for s, e, mid in spans[line - 1] if (s, e) == (at, at + len(piece))), None)
            if same is None and any(s < at + len(piece) and at < e for s, e, _ in spans[line - 1]):
                raise StoryboardError(f"{where}: mark {piece!r} overlaps another mark on formula {line}; marks may "
                                      "repeat the same term, but not share part of one")
            mid = same if same is not None else sum(len(v) for v in spans.values())
            if same is None:
                spans[line - 1].append((at, at + len(piece), mid))
            ids.setdefault(id(act), []).append((mid, line - 1))
    shown = []
    for i, tex in enumerate(blocks):
        for s, e, mid in sorted(spans[i], reverse=True):
            wrapped = f"\\htmlClass{{idr-m{mid}}}{{{tex[s:e]}}}"
            if tex[:s].rstrip().endswith(("^", "_")):       # x^2: the exponent must stay one group
                wrapped = "{" + wrapped + "}"
            tex = f"{tex[:s]}{wrapped}{tex[e:]}"
        plain = texmath.expand(blocks[i], own.optional)
        if from_source and numbers[i] is not False:        # the paper's own equation numbers, or none: never KaTeX's count
            tex, plain = texmath.renumbered(tex, numbers[i]), texmath.renumbered(plain, numbers[i])
            if numbers[i] is None:
                b.warn(where, f"formula {i + 1} is shown without its equation number: the number cannot be told from "
                              "this file alone (the paper counts by section, sets the counter, or pulls in other "
                              "files first). Do not say a number for it unless you read it in the paper's PDF")
        tex = texmath.expand(tex, own.optional)
        shown.append(tex)
        b.tex.append({"where": f"{where} formula {i + 1}", "tex": tex, "display": True, "seg": None, "strict": True,
                      "plain": plain, "marks": [blocks[i][s:e] for s, e, _ in spans[i]], "macros": own})

    b.macros = own
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
    return bool(re.fullmatch(r"\$?\s*[-+−~≈]?[\d][\d,]*(\.\d+)?\s*(%|x|×|ms|s|MB|KB|GB|bpc|bits?)?\s*\$?", cell.strip()))


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
            in_tex = name.lower().endswith((".tex", ".ltx"))
            if in_tex:
                b.macros = source.tex_macros(b.root, name, spec.get("ref"), spec.get("encoding"))
            header, aligns, rows, first_line = (source.tex_table if in_tex else source.md_table)(
                b.root, name, first, last, spec.get("ref"), spec.get("encoding"))
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
    marked = [x for x in b.tex if x.get("marks")]
    errors = texmath.validate([(x["tex"], x["display"], x.get("macros")) for x in b.tex]
                              + [(x["plain"], x["display"], x.get("macros")) for x in marked])
    if errors is None:
        b.warn("math", "no browser could be started to check the LaTeX; mistakes will show as red text")
        return []
    plain_ok = {id(x): not error for x, error in zip(marked, errors[len(b.tex):])}
    problems = []
    for item, error in zip(b.tex, errors):
        refused = _NOT_SHOWN.search(item["tex"]) if isinstance(item["tex"], str) else None
        if not error and refused:
            error = f"{refused.group(0)} is not something a formula in a video may contain"
        if not error:
            continue
        if item["strict"] and plain_ok.get(id(item)):       # the formula is fine; a mark on it is what breaks it
            pieces = ", ".join(repr(m) for m in item["marks"])
            problems.append(f"{item['where']}: a mark cannot be highlighted on its own ({pieces}): it is not a "
                            f"complete term of the formula. Mark a whole term, such as a full \\left( ... \\right) "
                            f"pair or a full fraction. (KaTeX said: {error})")
        elif item["strict"]:
            problems.append(f"{item['where']}: LaTeX error: {error}")
        else:
            b.warn(item["where"], f"{item['seg']['raw']!r} is not valid LaTeX ({error}); it is shown as plain text")
            seg = item["seg"]
            kept = {"text": seg["raw"], **({"mark": seg["mark"]} if "mark" in seg else {})}
            seg.clear()
            seg.update(kept)
    return problems


MOVE_STEPS = 96     # positions worked out along the way when a point travels
DRAW = 1.1          # seconds a curve takes to draw itself (see player.js)
PLOT_FIELDS = {"type", "heading", "sub", "beyond", "math", "beats", "expr", "name", "curves", "x", "y", "equal",
               "asymptotes", "xticks", "yticks", "xlabel", "ylabel", "source"}
# The fields of each kind of curve, keyed by the field that says which kind it is (looked for in this order).
CURVE_FIELDS = {"equation": {"equation"}, "r": {"r", "theta"}, "stages": {"stages"}, "vary": {"expr", "vary", "name"},
                "integral": {"integral", "from", "name"}, "t": {"x", "y", "t"}, "expr": {"expr", "name"}}
_PLACED = {"x", "y", "t", "root", "max", "min", "meet", "near"}
MARK_FIELDS = {"point": _PLACED | {"on", "as", "digits", "label", "side"},
               "tangent": _PLACED | {"on", "as", "digits", "label", "side"},
               "secant": {"x", "other", "approach", "seconds", "on", "as", "digits", "label", "side"},
               "shade": {"from", "to", "between", "grow", "seconds", "on", "as", "digits", "label"},
               "riemann": {"from", "to", "n", "rule", "on", "as", "digits", "label"},
               "arrow": {"from", "to", "on"},
               "move": {"from", "to", "tangent", "seconds", "on"}}
MAX_STAGES = 8      # formulas one changing curve may move through
MAX_RECTANGLES = 200
# Commands KaTeX only draws as red error text here (they need trust), or that would restyle the page.
_NOT_SHOWN = re.compile(r"\\(?:href|url|includegraphics|htmlId|htmlStyle|htmlData)(?![A-Za-z])")


def _plot(b: _Builder, spec: dict, kicker: str) -> Scene:
    """Curves on a pair of axes: functions of x, parametric curves and equations in x and y, with points,
    tangents, shaded areas and travelling points. Every number shown is worked out here from the formulas."""
    where = spec.get("heading") or "plot"

    def fail(message: str):
        raise StoryboardError(f"{where}: {message}")

    def num(value, what: str) -> tuple[float, str | None]:
        try:
            return plot.constant(value)
        except ValueError as problem:
            fail(f"{what}: {problem}")

    def span(value, what: str, example: str) -> tuple[float, float, bool]:
        if not (isinstance(value, list) and len(value) == 2):
            fail(f'{what} takes two values, the smaller first, as in {example}')
        (lo, lo_tex), (hi, hi_tex) = num(value[0], what), num(value[1], what)
        if not lo < hi:
            fail(f"{what} needs the smaller value first")
        return lo, hi, bool(lo_tex and "pi" in lo_tex or hi_tex and "pi" in hi_tex)

    _only(spec, PLOT_FIELDS, "a plot scene", where)
    given = spec.get("curves") or ([{"expr": spec["expr"], "name": spec.get("name")}] if spec.get("expr") else [])
    given = [{"expr": c} if isinstance(c, str) else c for c in given]
    for c in given:
        if isinstance(c, dict):
            kind = next((k for k in CURVE_FIELDS if k in c), "expr")
            _only(c, CURVE_FIELDS[kind], f"a curve written with \"{kind}\"", where)
    if not 1 <= len(given) <= MAX_CURVES:
        fail(f'a plot scene draws 1 to {MAX_CURVES} curves ("expr", or "curves": [...]), not {len(given)}')
    if "x" not in spec:
        fail('a plot scene needs "x": [from, to], the part of the x axis to show')
    x0, x1, x_pi = span(spec["x"], '"x"', '[-3, 3] or ["-2*pi", "2*pi"]')

    shapes = []
    try:
        for c in given:
            if not isinstance(c, dict):
                fail('a curve is a formula in x, or an object with "expr", with "x", "y" and "t", or with "equation"')
            if "equation" in c:
                shapes.append(plot.Implicit(c["equation"]))
            elif "r" in c:
                if "theta" not in c:
                    fail('a polar curve needs "r", a formula in theta, and "theta": [from, to]')
                t0, t1, _ = span(c["theta"], 'a curve\'s "theta"', '[0, "2*pi"]')
                shapes.append(plot.Polar(c["r"], t0, t1))
            elif "stages" in c:
                stages = c["stages"]
                if not (isinstance(stages, list) and 2 <= len(stages) <= MAX_STAGES and all(isinstance(v, str) for v in stages)):
                    fail(f'"stages" is a list of 2 to {MAX_STAGES} formulas in x that one curve moves through')
                shapes.append(plot.Changing(stages=stages))
            elif "vary" in c:
                vary = c["vary"]
                if not (isinstance(vary, dict) and len(vary) == 1 and re.fullmatch(r"[a-wyz]", next(iter(vary)))):
                    fail('"vary" names one letter of the formula and the values it runs between, as in {"k": [1, 4]}')
                letter = next(iter(vary))
                if not (isinstance(vary[letter], list) and len(vary[letter]) == 2):
                    fail('"vary" takes the two values the letter runs between, as in {"k": [1, 4]}')
                (lo, _), (hi, _) = num(vary[letter][0], '"vary"'), num(vary[letter][1], '"vary"')
                if lo == hi:
                    fail('"vary" needs two different values')
                shapes.append(plot.Changing(expr=c.get("expr"), letter=letter, lo=lo, hi=hi, name=c.get("name")))
            elif "integral" in c:
                of = c["integral"]
                if isinstance(of, bool) or not isinstance(of, int) or not 1 <= of <= len(shapes) or shapes[of - 1].kind != "function":
                    fail('"integral" is the number of an earlier curve in this scene that is a function of x; the new '
                         'curve is the area under it, as in {"integral": 1, "from": 0, "name": "A"}')
                if "from" not in c:
                    fail('"integral" needs "from", the x where the area starts at zero')
                start, start_tex = num(c["from"], '"from"')
                name = c.get("name")
                if name is not None and not re.fullmatch(r"[A-Za-z]", str(name)):
                    fail(f'a curve\'s "name" is one letter, as in A for A(x); not {name!r}')
                shapes.append(plot.Area(shapes[of - 1], start, x0, x1, name, start_tex))
            elif "t" in c:
                if not ("x" in c and "y" in c):
                    fail('a curve with "t" needs "x" and "y", two formulas in t')
                t0, t1, _ = span(c["t"], 'a curve\'s "t"', '[0, "2*pi"]')
                shapes.append(plot.Parametric(c["x"], c["y"], t0, t1))
            else:
                name = c.get("name")
                if name is not None and not re.fullmatch(r"[A-Za-z]", str(name)):
                    fail(f'a curve\'s "name" is one letter, as in f for f(x); not {name!r}')
                shapes.append(plot.Function(c.get("expr"), name))
    except ValueError as problem:
        if isinstance(problem, StoryboardError):
            raise
        fail(str(problem))

    y_pi = False
    if spec.get("y"):
        y0, y1, y_pi = span(spec["y"], '"y"', "[-2, 2]")
    else:
        seen = [(h, shape.bounded(x0, x1)) for shape in shapes for h in [shape.heights(x0, x1)] if len(h)]
        if not seen:
            fail('with only equations to draw, say which part of the y axis to show: "y": [from, to]')
        try:
            y0, y1 = plot.view_of([h for h, _ in seen], [whole for _, whole in seen])
        except ValueError as problem:
            fail(str(problem))
    wide, high = x1 - x0, y1 - y0

    curves = []
    for n, shape in enumerate(shapes, 1):
        if shape.kind == "changing":
            try:
                xs, frames = shape.frames(x0, x1, y0, y1)
            except ValueError as problem:
                fail(f"{shape.text!r}: {problem}")
            for k, tex in enumerate(shape.labels, 1):
                b.tex.append({"where": f"{where} curve {n} stage {k}", "tex": tex, "display": False, "seg": None, "strict": True})
            curves.append({"tex": shape.tex(), "draw": "stages", "xs": xs, "frames": frames,
                           "labels": shape.labels if len(shape.labels) > 1 else None, "texts": shape.texts, "lines": []})
            continue
        try:
            lines = shape.strokes(x0, x1, y0, y1)
        except ValueError as problem:
            fail(f"{shape.text!r} {problem}")
        if not any(x0 <= px <= x1 and y0 <= py <= y1 for line in lines for px, py in line):
            fail(f'{shape.text!r} is never inside the graph (x from {plot.number(x0)} to {plot.number(x1)}, '
                 f'y from {plot.number(y0)} to {plot.number(y1)}); change "x" or "y"')
        b.tex.append({"where": f"{where} curve {n}", "tex": shape.tex(), "display": False, "seg": None, "strict": True})
        curves.append({"tex": shape.tex(), "lines": lines, "draw": "wipe" if shape.kind == "function" else "trace"})

    def label(tex: str, what: str) -> str:
        b.tex.append({"where": f"{where} {what}", "tex": tex, "display": False, "seg": None, "strict": True})
        return tex

    def on_curve(item: dict, what: str) -> int:
        on = item.get("on", 1)
        if not isinstance(on, int) or isinstance(on, bool) or not 1 <= on <= len(shapes):
            fail(f'{what} is "on" curve {on!r}, but the scene has {len(shapes)}')
        if shapes[on - 1].kind == "changing":
            fail(f"{what} cannot sit on a curve that changes; draw the stage you mean as a curve of its own")
        return on - 1

    def function(i: int, what: str):
        if shapes[i].kind != "function":
            fail(f"{what} needs a function of x; curve {i + 1} is not one")
        return shapes[i].f

    def found(i: int, item: dict, what: str) -> dict:
        """A place the storyboard asks the engine to find, turned into the x it is at: a root, a highest or lowest
        point, or where two curves meet. The storyboard names it; it never types the number."""
        asked = [k for k in ("root", "max", "min", "meet") if k in item]
        if not asked:
            return item
        if len(asked) > 1 or "x" in item:
            fail(f'{what} takes one of "x", "root", "max", "min" or "meet"')
        key = asked[0]
        f = function(i, f'"{key}"')
        within = item["near"] if key == "meet" else item[key]
        lo, hi, _ = span(within, f'"{"near" if key == "meet" else key}"', "[0, 3], the part of the x axis to look in")
        if not (x0 - 1e-9 <= lo and hi <= x1 + 1e-9):
            fail(f"{what}: the range to look in must lie inside the graph's x range")
        try:
            if key == "root":
                x = plot.root(f, lo, hi)
            elif key == "meet":
                other = item["meet"]
                if not isinstance(other, int) or isinstance(other, bool) or not 1 <= other <= len(shapes) or other - 1 == i:
                    fail('"meet" is the number of the other curve, with "near": [from, to] to say where to look')
                g = function(other - 1, '"meet"')
                x = plot.root(lambda v: f(v) - g(v), lo, hi)
            else:
                x = plot.extremum(f, lo, hi, key == "max")
        except ValueError as problem:
            fail(f"{what}: {shapes[i].text!r} {problem} (x from {plot.number(lo)} to {plot.number(hi)})")
        return {**{k: v for k, v in item.items() if k not in ("root", "max", "min", "meet", "near")}, "x": x}

    def place(i: int, item: dict, what: str, key: str | None = None) -> tuple[float, float, float, str | None]:
        """Where on curve i an item sits: (x, y, parameter, LaTeX of an x that was written as an expression)."""
        shape = shapes[i]
        if shape.kind == "implicit":
            if key or "x" not in item or "y" not in item:
                fail(f'{what} on an equation needs both "x" and "y", a point the equation holds at')
            (px, _), (py, _) = num(item["x"], what), num(item["y"], what)
            gap, scale = shape.gap(px, py), shape.scale(px, py, wide, high)
            if gap != gap or abs(gap) > 1e-6 * max(scale, 1e-12):
                fail(f"{what}: ({plot.number(px)}, {plot.number(py)}) is not on {shape.text!r}")
            param, written = px, None
        else:
            want = key or ("t" if shape.kind == "parametric" else "x")
            if want not in item:
                fail(f'{what} on this curve needs "{want}"' + (', the value of t there' if want == "t" else ""))
            param, written = num(item[want], what)
            if shape.kind == "parametric" and not shape.t0 - 1e-9 <= param <= shape.t1 + 1e-9:
                fail(f"{what}: t = {plot.number(param)} is outside the curve's t range")
            px, py = shape.at(param)
            if px != px or py != py:
                fail(f"{what}: {shape.text!r} has no value at {want} = {plot.number(param)}")
            if shape.kind == "parametric":
                written = None
        if not (x0 - 1e-9 <= px <= x1 + 1e-9 and y0 - 1e-9 <= py <= y1 + 1e-9):
            fail(f"{what} at ({plot.number(px)}, {plot.number(py)}) is outside the graph; change \"x\" or \"y\" to include it")
        return float(px), float(py), float(param), written

    def heading_of(i: int, px: float, py: float, param: float) -> tuple[float, float, float]:
        """The direction of the tangent at a point, as (dx, dy), and how uncertain the slope dy/dx is.
        The curve classes look for the tangent instead of assuming one: a corner, a jump or a crossing has none."""
        shape = shapes[i]
        try:
            if shape.kind == "implicit":
                dx, dy, unsure = shape.direction(px, py, wide, high)
            else:
                dx, dy, unsure = shape.direction(param, wide, high)
        except ValueError as problem:
            fail(f"{shape.text!r} {problem} at ({plot.number(px)}, {plot.number(py)})")
        if dx != dx or dy != dy or (abs(dx) < 1e-12 and abs(dy) < 1e-12):
            fail(f"{shape.text!r} has no tangent at ({plot.number(px)}, {plot.number(py)})")
        if not plot.upright(dx, dy, wide, high):
            slope = dy / dx
            if unsure > 1e-3 * max(abs(slope), 1e-6 * high / wide):
                fail(f"the slope of {shape.text!r} at ({plot.number(px)}, {plot.number(py)}) cannot be worked out "
                     "reliably (the curve changes too fast there)")
            if abs(slope) <= 4 * unsure:
                dy = 0.0                                    # a slope of 1e-17 is zero with rounding noise on it
        return float(dx), float(dy), float(unsure)

    def figures(item: dict) -> int:
        """How many significant figures a mark's label shows. The narration quotes the same figures."""
        d = item.get("digits", 4)
        if isinstance(d, bool) or not isinstance(d, int) or not 1 <= d <= 6:
            fail('"digits" is how many significant figures the label shows, a whole number from 1 to 6')
        return d

    def shown_as(item: dict, kind: str) -> str:
        """Which label a mark carries: a point's "xy" (the default), "x" or "y"; anything's "none"."""
        choice = item.get("label", "xy" if kind == "point" else "on")
        allowed = ("xy", "x", "y", "none") if kind == "point" else ("on", "none")
        if choice not in allowed:
            fail(f'"label" on a {kind} is ' + (' or '.join(f'"{a}"' for a in allowed if a != "on")) + f"; not {choice!r}")
        return choice

    def side_of(item: dict) -> str | None:
        side = item.get("side")
        if side is not None and side not in ("left", "right", "above", "below"):
            fail(f'"side" is where the label sits by its point: "left", "right", "above" or "below"; not {side!r}')
        return side

    def about(value: float, unsure: float, d: int) -> str:
        return r"\approx" if plot.rounded(value, unsure, d) else "="

    def slope_tex(dx: float, dy: float, unsure: float, d: int = 4) -> str:
        if plot.upright(dx, dy, wide, high):
            return r"\text{vertical}"
        slope = dy / dx
        return rf"\text{{slope}} {about(slope, unsure, d)} {plot.number_tex(slope, d)}"

    def point_tex(px: float, py: float, written: str | None, d: int = 4) -> str:
        return rf"\left({written or plot.number_tex(px, d)},\ {plot.number_tex(py, d)}\right)"

    def quiet(i: int, param: float, px: float, py: float) -> tuple[float, float]:
        """The point as it is labelled: a coordinate that is only rounding noise (sin(pi) = 1.2e-16) is zero."""
        shape = shapes[i]
        if shape.kind == "function":
            return px, plot.settled(shape.f, param)
        if shape.kind == "parametric":
            return plot.settled(shape.fx, param), plot.settled(shape.fy, param)
        return px, py

    marks: list[dict] = []
    owner: dict[int, list[tuple[str, int]]] = {}
    moves: dict[int, dict] = {}
    numbers: dict[int, dict[str, float]] = {}      # mark -> the numbers it shows, for {placeholders} in the narration
    named: dict[str, int] = {}
    shown_to: dict[int, int] = {}                  # mark -> the significant figures its label shows
    made: dict[int, list[int]] = {}                # beat -> the marks made in it and in its cues
    # Which of the three things on a graph each action replaces: one set of points, one line, one filled region.
    slot_of = {"point": "point", "tangent": "tangent", "secant": "tangent", "shade": "shade", "riemann": "shade",
               "move": "point", "arrow": "arrow"}
    example = {"point": '{"x": 1}', "tangent": '{"x": 1}', "secant": '{"x": 1, "other": 3}',
               "shade": '{"from": 0, "to": 2}', "riemann": '{"from": 0, "to": 2, "n": 8}', "move": '{"from": -2, "to": 2}',
               "arrow": '{"from": 1, "to": -1.4}'}

    def add(act: dict, beat: dict, slot: str, mark: dict, item: dict, shows: dict | None = None) -> int:
        if "label" in item and mark["kind"] not in ("move", "arrow"):
            if shown_as(item, mark["kind"]) == "none":     # nothing on screen, so nothing for the narration to quote
                mark.pop("tex", None)
                shows = {}
        if item.get("side") is not None:
            mark["side"] = side_of(item)
        marks.append(mark)
        mid = len(marks) - 1
        owner.setdefault(id(act), []).append((slot, mid))
        numbers[mid] = shows or {}
        shown_to[mid] = figures(item)
        made.setdefault(id(beat), []).append(mid)
        name = item.get("as")
        if name is not None:
            if not (isinstance(name, str) and re.fullmatch(r"[A-Za-z]\w*", name)):
                fail(f'"as" names a mark so the narration can quote its numbers, as in "as": "p"; not {name!r}')
            if name in named and numbers[named[name]] != numbers[mid]:
                fail(f'two different marks are named "{name}"')
            named[name] = mid
        return mid

    def growing(mid: int, item: dict, height, lo: float, hi: float, area: float, unsure: float, d: int) -> None:
        """An area that fills in from its left edge: the running total at each step on the way, worked out the
        same way as the whole. The last step is the whole area, written as its label writes it."""
        if not item.get("grow"):
            return
        if "tex" not in marks[mid]:
            fail('a growing area shows its running total, so it cannot have "label": "none"')
        try:
            running = plot.Integral(height, lo, lo, hi)
        except ValueError as problem:
            fail(f"the area cannot grow: the curve {problem}")
        steps = []
        for k in range(MOVE_STEPS + 1):
            x = lo + (hi - lo) * k / MOVE_STEPS
            steps.append([plot.tidy(x, wide), f"area ≈ {plot.fixed(running(x))}"])
        steps[-1][1] = f"area {'≈' if plot.rounded(area, unsure, d) else '='} {plot.minus(plot.number(area, d))}"
        marks[mid]["grow"] = steps
        moves[mid] = item

    # Everything drawn on a curve is worked out from its formula here, never typed into the storyboard.
    for beat in spec.get("beats", []):
      for act in [beat, *beat.get("cues", [])]:
        for kind in slot_of:
            value = act.get(kind)
            if value is None or value == []:
                continue
            if not isinstance(value, (dict, list)) or value == {}:
                fail(f'"{kind}" takes an object such as {example[kind]}, or a list of them (null clears it); not {value!r}')
            for item in [value] if isinstance(value, dict) else value:
                if not isinstance(item, dict) or not item:
                    fail(f'"{kind}" takes an object such as {example[kind]}, or a list of them; not {item!r}')
                _only(item, MARK_FIELDS[kind], f'"{kind}"', where)
                if kind == "shade" and "between" in item:
                    pair = item["between"]
                    if not (isinstance(pair, list) and len(pair) == 2 and all(isinstance(v, int) and not isinstance(v, bool)
                                                                              and 1 <= v <= len(shapes) for v in pair) and pair[0] != pair[1]):
                        fail('"between" is the numbers of two curves, as in [1, 2]')
                    i, other = pair[0] - 1, pair[1] - 1
                    f, g = function(i, '"shade"'), function(other, '"shade"')
                    if "from" not in item or "to" not in item:
                        fail('"shade" needs "from" and "to", two x values')
                    lo, hi, _ = span([item["from"], item["to"]], '"shade"', '{"from": 0, "to": 1, "between": [1, 2]}')
                    for k in (i, other):
                        place(k, {"x": lo}, "the shaded area"), place(k, {"x": hi}, "the shaded area")
                    between = f"between x = {plot.number(lo)} and {plot.number(hi)}"
                    try:
                        area, unsure = plot.area(lambda xs: np.abs(np.asarray(f(xs)) - np.asarray(g(xs))), lo, hi)
                    except ValueError:
                        fail(f"the area between the curves {between} cannot be measured: one of them shoots off or swings too fast there")
                    if area != area:
                        fail(f"one of the curves has no value somewhere {between}, so there is no area to shade")
                    xs = [lo + (hi - lo) * k / 160 for k in range(161)]
                    edge = lambda fn: [[plot.tidy(a, wide), plot.tidy(min(max(v, y0), y1), high)] for a, v in zip(xs, fn(xs).tolist())]
                    d = figures(item)
                    mid = add(act, beat, "shade", {"kind": "shade", "curve": i, "outline": edge(f), "base": edge(g),
                                                   "tex": label(rf"\text{{area}} {about(area, unsure, d)} {plot.number_tex(area, d)}", "area")},
                              item, {"area": area})
                    growing(mid, item, lambda xs: np.abs(np.asarray(f(xs)) - np.asarray(g(xs))), lo, hi, area, unsure, d)
                    continue
                i = on_curve(item, f"a {kind}")
                shape = shapes[i]
                if kind == "shade":
                    f = function(i, '"shade"')
                    if "from" not in item or "to" not in item:
                        fail('"shade" needs "from" and "to", two x values')
                    lo, hi, _ = span([item["from"], item["to"]], '"shade"', '{"from": 0, "to": 2}')
                    place(i, {"x": lo}, "the shaded area"), place(i, {"x": hi}, "the shaded area")
                    between = f"between x = {plot.number(lo)} and {plot.number(hi)}"
                    try:
                        area, unsure = f.area(lo, hi)
                    except ValueError as problem:
                        reason = ("the curve shoots off without bound inside that range, so there is no area to measure" if "bound" in str(problem)
                                  else "it jumps or swings too fast there for the area to be measured")
                        fail(f"the area under {shape.text!r} {between} cannot be shown: {reason}")
                    if area != area:
                        fail(f"{shape.text!r} has no value somewhere {between}, so there is no area to shade")
                    xs = [lo + (hi - lo) * k / 160 for k in range(161)]
                    ys = [min(max(v, y0), y1) for v in f(xs).tolist()]
                    d = figures(item)
                    mid = add(act, beat, "shade", {"kind": "shade", "curve": i,
                                                   "outline": [[plot.tidy(a, wide), plot.tidy(v, high)] for a, v in zip(xs, ys)],
                                                   "tex": label(rf"\text{{area}} {about(area, unsure, d)} {plot.number_tex(area, d)}", "area")},
                              item, {"area": area})
                    growing(mid, item, f, lo, hi, area, unsure, d)
                elif kind == "riemann":
                    f = function(i, '"riemann"')
                    if "from" not in item or "to" not in item:
                        fail('"riemann" needs "from" and "to", two x values, and "n", the number of rectangles')
                    lo, hi, _ = span([item["from"], item["to"]], '"riemann"', example[kind])
                    count, rule = item.get("n"), item.get("rule", "left")
                    if not isinstance(count, int) or isinstance(count, bool) or not 1 <= count <= MAX_RECTANGLES:
                        fail(f'"riemann": "n" is the number of rectangles, a whole number from 1 to {MAX_RECTANGLES}')
                    if rule not in ("left", "right", "mid"):
                        fail('"riemann": "rule" says where each rectangle touches the curve: "left", "right" or "mid"')
                    place(i, {"x": lo}, "the Riemann sum"), place(i, {"x": hi}, "the Riemann sum")
                    width = (hi - lo) / count
                    shift = {"left": 0.0, "right": 1.0, "mid": 0.5}[rule]
                    heights = [float(f(lo + (k + shift) * width)) for k in range(count)]
                    if any(h != h or math.isinf(h) for h in heights):
                        fail(f"{shape.text!r} has no value at one of the rectangles between x = {plot.number(lo)} and {plot.number(hi)}")
                    total = math.fsum(heights) * width
                    d = figures(item)
                    add(act, beat, "shade", {"kind": "riemann", "curve": i,
                                             "rects": [[plot.tidy(lo + k * width, wide), plot.tidy(lo + (k + 1) * width, wide),
                                                        plot.tidy(min(max(h, y0), y1), high)] for k, h in enumerate(heights)],
                                             "tex": label(rf"n = {count}:\ \text{{sum}} {about(total, 0.0, d)} {plot.number_tex(total, d)}", "sum")},
                        item, {"sum": total, "n": float(count)})
                elif kind == "secant":
                    f = function(i, '"secant"')
                    if "x" not in item or "other" not in item:
                        fail('"secant" needs "x" and "other", the x values of the two points the line goes through')
                    ax, ay, a, _ = place(i, {"x": item["x"]}, "the secant")
                    bx, by, far, _ = place(i, {"x": item["other"]}, "the secant")
                    if a == far:
                        fail('"secant" needs two different points; for the line at one point use "tangent"')
                    if not item.get("approach"):
                        slope = (by - ay) / (bx - ax)
                        add(act, beat, "tangent", {"kind": "tangent", "curve": i, "x": ax, "y": ay, "dx": 1.0, "dy": slope,
                                                   "other": [bx, by], "tex": label(slope_tex(1.0, slope, 0.0, figures(item)), "slope")},
                            item, {"slope": slope, "x": ax, "y": ay})
                        continue
                    # The second point slides to the first. Each line on the way is a true secant; the last is the tangent.
                    steps = []
                    for k in range(MOVE_STEPS + 1):
                        at = far + (a - far) * k / MOVE_STEPS
                        px, py, param, _ = place(i, {"x": at}, "the sliding point of the secant")
                        if k < MOVE_STEPS:
                            dx, dy = 1.0, (py - ay) / (px - ax)
                        else:
                            dx, dy, _ = heading_of(i, ax, ay, a)
                        steps.append([plot.tidy(px, wide), plot.tidy(py, high), dx, dy,
                                      f"({plot.fixed(px)}, {plot.fixed(py)})", plot.slope_text(dx, dy, wide, high)])
                    if plot.upright(steps[-1][2], steps[-1][3], wide, high):
                        fail("the tangent the secant closes in on is vertical, so its slope has no value to approach")
                    mid = add(act, beat, "tangent", {"kind": "move", "curve": i, "steps": steps, "tangent": True, "anchor": [ax, ay]},
                              item, {"slope": steps[-1][3] / steps[-1][2], "x": ax, "y": ay})
                    moves[mid] = item
                elif kind == "arrow":
                    if shape.kind == "implicit":
                        fail('"arrow" joins two points of a function of x or a curve in t, not of an equation')
                    key = "t" if shape.kind == "parametric" else "x"
                    if "from" not in item or "to" not in item:
                        fail(f'"arrow" needs "from" and "to", the {key} of the point it leaves and of the point it lands on')
                    ax, ay, a, _ = place(i, {key: item["from"]}, "the start of the arrow", key)
                    bx, by, far, _ = place(i, {key: item["to"]}, "the end of the arrow", key)
                    if a == far:
                        fail('"arrow" needs two different points')
                    add(act, beat, "arrow", {"kind": "arrow", "curve": i, "from": [ax, ay], "to": [bx, by]}, item)
                elif kind == "move":
                    if shape.kind == "implicit":
                        fail('"move" follows a function of x or a curve in t, not an equation')
                    key = "t" if shape.kind == "parametric" else "x"
                    if "from" not in item or "to" not in item:
                        fail(f'"move" needs "from" and "to", two values of {key}')
                    (start, _), (stop, _) = num(item["from"], '"move"'), num(item["to"], '"move"')
                    if start == stop:
                        fail('"move" needs "from" and "to" to differ')
                    steps = []
                    for k in range(MOVE_STEPS + 1):
                        at = start + (stop - start) * k / MOVE_STEPS
                        px, py, param, _ = place(i, {key: at}, "the travelling point", key)
                        dx, dy, _ = heading_of(i, px, py, param) if item.get("tangent") else (0.0, 0.0, 0.0)
                        steps.append([plot.tidy(px, wide), plot.tidy(py, high), dx, dy,
                                      f"({plot.fixed(px)}, {plot.fixed(py)})",
                                      plot.slope_text(dx, dy, wide, high) if item.get("tangent") else ""])
                    mid = add(act, beat, "point", {"kind": "move", "curve": i, "steps": steps, "tangent": bool(item.get("tangent"))}, item)
                    moves[mid] = item
                    if item.get("tangent"):
                        owner[id(act)].append(("tangent", mid))
                else:
                    item = found(i, item, f"the {kind}")
                    px, py, param, written = place(i, item, f"the {kind}")
                    if kind == "point":
                        qx, qy = quiet(i, param, px, py)
                        only, d = shown_as(item, "point"), figures(item)
                        tex = {"x": f"x = {written or plot.number_tex(qx, d)}", "y": f"y = {plot.number_tex(qy, d)}"}.get(
                            only, point_tex(qx, qy, written, d))
                        add(act, beat, "point", {"kind": "point", "curve": i, "x": px, "y": py, "tex": label(tex, "point"),
                                                 **({"only": only} if only in ("x", "y") else {})},
                            item, {k: v for k, v in (("x", qx), ("y", qy)) if only in ("xy", k)})
                    else:
                        dx, dy, unsure = heading_of(i, px, py, param)
                        shows = {"x": px, "y": py}
                        if not plot.upright(dx, dy, wide, high):
                            shows["slope"] = dy / dx
                        add(act, beat, "tangent", {"kind": "tangent", "curve": i, "x": px, "y": py, "dx": dx, "dy": dy,
                                                   "tex": label(slope_tex(dx, dy, unsure, figures(item)), "slope")}, item, shows)

    # A number the engine worked out is quoted in the narration by name, never retyped: "{p.y}" is the y of the
    # mark named p, "{slope}" the slope of the only tangent in that sentence. So voice and screen cannot disagree.
    def quoted(text: str, beat: dict) -> str:
        mine = made.get(id(beat), [])

        def fill(m: re.Match) -> str:
            first, field, digits = m.group(1), m.group(2), m.group(3)
            if field is None:
                having = [mid for mid in mine if first in numbers[mid]]
                distinct = {numbers[mid][first] for mid in having}
                if not having:
                    known = sorted({k for mid in mine for k in numbers[mid]}) or ["nothing: no mark is made in this sentence"]
                    fail(f"the narration quotes {{{first}}}, but the marks in that sentence give {', '.join(known)}"
                         + (f'; for the mark named "{first}" say which number, as in {{{first}.y}}' if first in named else ""))
                if len(distinct) > 1:
                    fail(f'the narration quotes {{{first}}}, but several marks in that sentence have one; name them with "as" '
                         f"and write {{name.{first}}}")
                value, mid = numbers[having[0]][first], having[0]
            else:
                if first not in named:
                    fail(f'the narration quotes {{{first}.{field}}}, but no mark is named "{first}" (give it "as": "{first}")')
                if field not in numbers[named[first]]:
                    fail(f'the mark "{first}" has no {field}; it has {", ".join(sorted(numbers[named[first]])) or "no numbers"}')
                value, mid = numbers[named[first]][field], named[first]
            if digits and int(digits) != shown_to[mid]:      # a caption that says 5.7 under a label that says 5.711
                fail(f'the narration quotes {m.group(0)} to {digits} figures, but the label on screen shows '
                     f'{shown_to[mid]}; to round both, put "digits": {digits} on the mark and write '
                     f'{m.group(0).split(":")[0]}}}')
            return plot.minus(plot.number(value, shown_to[mid]))

        return re.sub(r"\{([A-Za-z]\w*)(?:\.([a-z]+))?(?::([1-9]))?\}", fill, text)

    for beat in spec.get("beats", []):
        for key in ("say", "speak"):
            if isinstance(beat.get(key), str) and "{" in beat[key]:
                beat[key] = quoted(beat[key], beat)

    # An asymptote is a claim about a curve, so it is checked against one before the dashed line is drawn.
    guides = []
    for item in spec.get("asymptotes") or []:
        if not (isinstance(item, dict) and len([k for k in ("x", "y") if k in item]) == 1):
            fail('"asymptotes" is a list of {"x": 1} (a vertical line) and {"y": 0} (a horizontal one)')
        functions = [shape for shape in shapes if shape.kind == "function"]
        if "x" in item:
            at, written = num(item["x"], "an asymptote")
            if not x0 < at < x1:
                fail(f"the asymptote x = {plot.number(at)} is outside the graph")
            if functions and not any(plot.runs_away(shape.f, at - wide * 0.02, at + wide * 0.02) for shape in functions):
                fail(f"no curve shoots off at x = {plot.number(at)}, so that is not a vertical asymptote")
            guides.append({"x": at, "label": f"x = {plot.minus(plot.number(at))}"})
        else:
            at, written = num(item["y"], "an asymptote")
            if not y0 < at < y1:
                fail(f"the asymptote y = {plot.number(at)} is outside the graph")

            def nears(f) -> bool:                          # at one end of the x range the curve is close, and closing in
                for end, inner in ((x1, x1 - wide * 0.2), (x0, x0 + wide * 0.2)):
                    gap, before = abs(float(f(end)) - at), abs(float(f(inner)) - at)
                    if gap == gap and before == before and gap <= 0.06 * high and gap < before:
                        return True
                return False
            if functions and not any(nears(shape.f) for shape in functions):
                fail(f"no curve closes in on y = {plot.number(at)} towards either end of the x range, so that is not shown "
                     "as a horizontal asymptote; widen \"x\" if the curve only gets there further out")
            guides.append({"y": at, "label": f"y = {plot.minus(plot.number(at))}"})
    for name_, text in (("xlabel", spec.get("xlabel")), ("ylabel", spec.get("ylabel"))):
        if text is not None and (not isinstance(text, str) or len(text) > 24):
            fail(f'"{name_}" is a short name for the axis (up to 24 characters); put the rest in the heading or the narration')

    def axis_ticks(lo: float, hi: float, about: int, in_pi: bool, choice, across: bool = False) -> list[list]:
        if choice not in (None, "pi", "numbers"):
            fail('"xticks" and "yticks" are "pi" or "numbers"')
        if choice == "pi" or (in_pi and choice != "numbers"):
            marks_ = [[v, text] for v, text in plot.pi_ticks(lo, hi, about)]
            if len(marks_) >= 2:                            # a range too small for two marks in pi gets numbers
                return marks_
        room = (115 if is_wide else 62) if across else 10 ** 6       # characters that fit along the x axis
        for fewer in (about, max(about // 2, 3), 3, 2):
            for digits in (4, 6, 8, 10):                    # 100000001 and 100000002 need more than four digits
                marks_ = [[v, plot.minus(plot.number(v, digits))] for v in plot.ticks(lo, hi, fewer)]
                if len({text for _, text in marks_}) == len(marks_):
                    break
            if sum(len(text) + 3 for _, text in marks_) <= room:
                break
        if len({text for _, text in marks_}) < len(marks_):
            fail(f"the axis from {lo!r} to {hi!r} is too short for how far it is from "
                 "zero: its marks would all read the same. Shift the formula so the range starts near zero")
        return marks_

    is_wide = b.fmt == "wide"
    on = _math_on(b, spec)
    scene = b.scene("plot", kicker, spec, x=[x0, x1], y=[y0, y1], curves=curves, marks=marks, equal=bool(spec.get("equal")),
                    xticks=axis_ticks(x0, x1, 10 if is_wide else 6, x_pi, spec.get("xticks"), across=True),
                    yticks=axis_ticks(y0, y1, 7 if is_wide else 9, y_pi, spec.get("yticks")),
                    xlabel=spec.get("xlabel", "x"), ylabel=spec.get("ylabel", "y"), guides=guides,
                    credit=b.rich(spec.get("source"), on, where))
    scene.sfx.append((0.0, "whoosh"))
    ops = scene.payload["ops"]
    clock = _Clock(b, scene, where)
    stage = _Stage(scene, len(curves), "curve", _staged(spec))
    shown: dict[str, list[int]] = {"point": [], "tangent": [], "shade": [], "arrow": []}
    moved: set[int] = set()
    for beat in spec.get("beats", []):
        timed = clock.beat(beat)
        spoken_until = clock.t - GAP                    # when this beat's sentence ends
        for t, act, src in timed:
            if "reveal" in act:
                stage.upto(act["reveal"], t)
            mine = owner.get(id(src), [])
            changing = [n for n, shape in enumerate(shapes) if shape.kind == "changing"]
            for key in ("stage", "sweep"):
                if key not in act:
                    continue
                value = act[key]
                which = value.get("curve") if isinstance(value, dict) else None
                if which is None:
                    which = changing[0] + 1 if changing else None
                if not isinstance(which, int) or which - 1 not in changing:
                    fail(f'"{key}" moves a curve that changes (one with "stages" or "vary"); this scene has none'
                         if not changing else f'"{key}": curve {which!r} is not a curve that changes')
                frames = curves[which - 1]["frames"]
                moved.add(which - 1)
                if key == "stage":
                    to = value.get("to") if isinstance(value, dict) else value
                    if curves[which - 1]["texts"] or not isinstance(to, int) or isinstance(to, bool) or not 1 <= to <= len(frames):
                        fail(f'"stage" is the number of the formula in "stages" to move to, from 1 to {len(frames)}'
                             if not curves[which - 1]["texts"] else '"stage" is for a curve with "stages"; a curve with "vary" takes "sweep"')
                    ops.append({"op": "stage", "t": t, "curve": which - 1, "to": to - 1, "dur": 0.9})
                    scene.sfx.append((t, "tick"))
                else:
                    if not curves[which - 1]["texts"]:
                        fail('"sweep" is for a curve with "vary"; a curve with "stages" takes "stage"')
                    seconds = value.get("seconds") if isinstance(value, dict) else None
                    if seconds is not None and not (isinstance(seconds, (int, float)) and 0.5 <= seconds <= 20):
                        fail('"sweep": "seconds" is a number from 0.5 to 20')
                    run = float(seconds) if seconds else max(1.5, spoken_until - t - 0.4)
                    ops.append({"op": "stage", "t": round(t + 0.2, 3), "curve": which - 1, "to": len(frames) - 1,
                                "dur": round(run, 3), "steady": True})
                    clock.t = max(clock.t, t + 0.2 + run + GAP)           # the scene waits for the sweep to finish
            kept: dict[int, int] = {}
            for kind in shown:
                touched = any(slot_of[k] == kind for k in slot_of if k in act and k != "move") \
                    or ("move" in act and (kind == "point" or any(k == kind for k, _ in mine)))
                if not touched:
                    continue
                for mid in shown[kind]:                # a new point, tangent or area replaces the ones of its kind,
                    twin = next((m for k, m in mine      # but one that is listed again as it was simply stays
                                 if k == kind and m not in kept and m != mid and marks[m] == marks[mid]
                                 and m not in moves), None)
                    if twin is not None:
                        kept[twin] = mid
                    elif not any(m == mid for _, m in mine):
                        ops.append({"op": "hide", "t": t, "mark": mid})
                shown[kind] = [kept.get(mid, mid) for k, mid in mine if k == kind]
            started = set(kept)
            fresh = [(kind, mid) for kind, mid in mine if mid not in kept]
            for j, (kind, mid) in enumerate(fresh):
                if mid in started:
                    continue
                started.add(mid)
                if marks[mid]["curve"] >= stage.visible:
                    b.warn(where, f"a {marks[mid]['kind']} is on curve {marks[mid]['curve'] + 1} before that curve is revealed")
                at = round(t + 0.12 + (j * 0.3 if mid not in moves else 0), 3)
                drawn = max((op["t"] + DRAW for op in ops if op["op"] == "reveal" and op.get("curve") == marks[mid]["curve"]),
                            default=0.0)
                at = round(max(at, drawn), 3)              # a mark waits for its curve: an area with no curve over it is a blob
                ops.append({"op": "show", "t": at, "mark": mid})
                scene.sfx.append((at, "mark" if kind == "shade" else "tick"))
                if mid in moves:
                    item = moves[mid]
                    seconds = item.get("seconds")
                    if seconds is not None and not (isinstance(seconds, (int, float)) and 0.5 <= seconds <= 20):
                        fail('"seconds" is a number from 0.5 to 20')
                    travel = float(seconds) if seconds else max(1.5, spoken_until - at - 0.5)
                    ops.append({"op": "travel", "t": round(at + 0.35, 3), "mark": mid, "dur": round(travel, 3)})
                    clock.t = max(clock.t, at + 0.35 + travel + GAP)      # the scene waits for the point to arrive
    stage.upto(len(curves), clock.t)
    for n, shape in enumerate(shapes):
        if shape.kind == "changing" and n not in moved:
            b.warn(where, f'curve {n + 1} can change but never does; give a beat "stage" or "sweep", or draw it as a plain curve')
    first = min((op["t"] for op in ops if op["op"] == "reveal"), default=0.0)
    if first > LEAD + 1.0:
        b.warn(where, f"the graph is empty for the first {first:.1f} seconds; draw the first curve when the first "
                      "sentence starts")
    clock.finish()
    return scene


def _from(module: str, name: str):
    """A scene that lives in a module of its own. That module builds on this one, so it is loaded when first used."""
    def make(b: _Builder, spec: dict, kicker: str) -> Scene:
        import importlib
        return getattr(importlib.import_module(f"{__package__}.{module}"), name)(b, spec, kicker)
    return make


SCENES = {"code": _code, "diff": _diff, "quote": _quote, "image": _image, "flow": _flow, "compare": _compare,
          "stats": _stats, "steps": _steps, "math": _math, "table": _table, "plot": _plot,
          "diagram": _from("diagrams", "_diagram"), "array": _from("diagrams", "_array"),
          "sequence": _from("diagrams", "_sequence"), "chart": _from("chart", "_chart")}
OVERVIEW_FROM = 3   # videos with this many chapters open with a card that lists them
NO_SOURCE = "No source document  ·  explained from general knowledge"   # on the opening card of such a video


def _shows_source(spec: dict) -> bool:
    """Whether a scene puts the source itself on screen (a file, a page, a picture), as opposed to an explanation."""
    kind = spec.get("type")
    if kind == "code":
        return not spec.get("example")
    return kind in ("diff", "quote", "image", "chart") or (kind in ("math", "table") and bool(spec.get("file")))


def _basis(storyboard: dict) -> bool:
    """True when the video has no source and says so. A video must either show its source or declare this."""
    declared = storyboard.get("source")
    if declared not in (None, "none"):
        raise StoryboardError(f'"source" at the top of a storyboard can only be "none" (there is no source, and the '
                              f'opening card will say so), not {declared!r}')
    specs = [spec for chapter in storyboard["chapters"] for spec in chapter.get("scenes") or []]
    shown = [spec for spec in specs if _shows_source(spec)]
    if declared == "none" and shown:
        first = shown[0]
        raise StoryboardError(f'"source" is "none", but the {first.get("type")} scene '
                              f'{first.get("heading") or first.get("file") or first.get("url") or ""!r} shows a source; '
                              'remove "source": "none", and mark the scenes that go past the source with "beyond": true')
    instructions = all(spec.get("type") == "steps" for spec in specs)      # a help video: nothing is being explained
    if declared is None and not shown and specs and not instructions:
        raise StoryboardError('no scene shows a source (code, diff, quote, image, chart, or math or table read from a file). '
                              'Show the source; or, if the user gave none and this is your own explanation, put '
                              '"source": "none" at the top of the storyboard so the video says so')
    return declared == "none"


def build(storyboard: dict, root: Path, theme: str, narrator, captions: bool = True,
          fmt: str = "wide", pronounce: dict | None = None, home: Path | None = None) -> tuple[list[Scene], list[str]]:
    """All scenes of the video in order, plus warnings about things that may not read well.

    `root` is the source folder; `home` is the storyboard's folder (the same, unless given)."""
    b = _Builder(root, theme, narrator, captions, fmt)
    b.home = home or root
    b.math_default = bool(storyboard.get("math", True))
    try:
        b.pronounce = {**speech.table(pronounce, "settings"), **speech.table(storyboard.get("pronounce"), "storyboard")}
    except ValueError as problem:
        raise StoryboardError(str(problem)) from None
    scenes: list[Scene] = []
    problems: list[str] = []
    if not storyboard.get("chapters"):
        raise StoryboardError("the storyboard has no chapters")
    unsourced = _basis(storyboard)
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
        # "beyond" marks what is not from the source, in a video that has one: the header says so on screen.
        # With no source at all, the opening card has said it for the whole video.
        card.payload["beyond"] = bool(chapter.get("beyond")) and not unsourced
        for spec in chapter["scenes"]:
            make = SCENES.get(spec.get("type"))
            if not make:
                raise StoryboardError(f"unknown scene type {spec.get('type')!r}; use one of {', '.join(SCENES)}")
            beyond = bool(chapter.get("beyond") or spec.get("beyond") or (spec.get("type") == "code" and spec.get("example")))
            if _shows_source(spec) and (chapter.get("beyond") or spec.get("beyond")):
                problems.append(f'chapter {n}, {spec.get("heading") or spec["type"]}: this scene shows the source, so it '
                                'cannot be "beyond" it; put "beyond" on the scenes that are your own explanation')
                continue
            b.macros = texmath.Macros()
            try:
                _check_beats(spec, spec.get("heading") or spec["type"])
                scenes.append(make(b, spec, kicker))
                scenes[-1].payload["beyond"] = beyond and not unsourced
            except KeyError as missing:
                problems.append(f"chapter {n}, {spec['type']} scene: missing field {missing}")
            except (ValueError, FileNotFoundError) as problem:      # report every scene's problem in one run
                named = isinstance(problem, (StoryboardError, FileNotFoundError))
                problems.append(str(problem) if named else f"{spec.get('heading') or spec['type']}: {problem}")
            except (TypeError, AttributeError, OverflowError, ZeroDivisionError, IndexError) as problem:
                # A field holds the wrong kind of value (a number where a list belongs). Say which scene, not a traceback.
                listed = ("guides/math.md" if spec["type"] in ("math", "plot") else "guides/diagrams.md"
                          if spec["type"] in ("diagram", "array", "sequence", "chart") else "SKILL.md section 4")
                problems.append(f"chapter {n}, {spec.get('heading') or spec['type']} ({spec['type']} scene): a field has "
                                f"the wrong kind of value ({type(problem).__name__}: {problem}); compare the scene with "
                                f"its fields in {listed}")
    problems += _check_math(b)
    if problems:
        raise StoryboardError("\nerror: ".join(problems))
    scenes[0].payload["opening"] = True               # drawn in full from the first frame (see player.js)
    if unsourced:
        scenes[0].payload["basis"] = NO_SOURCE
    return scenes, b.warnings
