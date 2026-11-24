"""Command line.

    python -m idr doctor                      check the machine; names the help video for anything missing
    python -m idr check   storyboard.json     validate, list scenes and estimated length (no voice, no video)
    python -m idr preview storyboard.json     draw one frame per scene into contact sheets to look at
    python -m idr render  storyboard.json     make the video
    python -m idr voices                      list narration voices
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

from . import env   # standard library only; everything heavier is imported inside the commands

CONFIG = ".i-dont-read.json"
DEFAULTS = {"theme": "light", "format": "wide", "voice": "af_heart", "speed": 1.0, "captions": True}


class Blocked(SystemExit):
    """The render cannot go ahead; the message names the help video to send instead."""


def settings(storyboard: dict, root: Path, args) -> dict:
    """Command line beats the storyboard, which beats the project's config file, which beats defaults."""
    out = dict(DEFAULTS)
    config = root / CONFIG
    if config.is_file():
        out.update({k: v for k, v in json.loads(config.read_text(encoding="utf-8")).items() if k in DEFAULTS})
    out.update({k: storyboard[k] for k in DEFAULTS if k in storyboard})
    out.update({k: getattr(args, k) for k in DEFAULTS if getattr(args, k, None) is not None})
    if out["theme"] not in ("light", "dark"):
        raise ValueError(f"theme must be light or dark, not {out['theme']!r}")
    if out["format"] not in ("wide", "tall"):
        raise ValueError(f"format must be wide or tall, not {out['format']!r}")
    return out


def _tag(opts: dict) -> str:
    """What distinguishes this render's files: theme, plus the format when it is not the default."""
    return opts["theme"] + ("_tall" if opts["format"] == "tall" else "")


def _load(args) -> tuple[dict, Path, dict, Path]:
    board_path = Path(args.storyboard).resolve()
    storyboard = json.loads(board_path.read_text(encoding="utf-8"))
    root = Path(args.root).resolve() if args.root else board_path.parent
    return storyboard, root, settings(storyboard, root, args), board_path


def _need_tools() -> None:
    """Stop before filming if ffmpeg or a browser is missing, pointing at the video that explains the fix."""
    if not shutil.which("ffmpeg"):
        raise Blocked(f"blocked: ffmpeg is not installed. Send the user this video instead: {env.HELP / 'ffmpeg.mp4'}")
    if not env.find_chrome() and not env.playwright_chromium():
        raise Blocked(f"blocked: no Chrome or Chromium found. Send the user this video instead: {env.HELP / 'chrome.mp4'}")


def _report(scenes: list, warnings: list[str], estimated: bool) -> float:
    total = sum(s.duration for s in scenes)
    for i, s in enumerate(scenes, 1):
        p = s.payload
        mark = f"== {s.chapter}" if s.chapter else f"   {p.get('heading') or ''}"
        print(f"{i:>3}  {p['type']:<8}{s.duration:>6.1f}s  {mark}")
    print(f"total {'about ' if estimated else ''}{total:.0f}s ({total / 60:.1f} min), {len(scenes)} scenes")
    for w in warnings:
        print(f"warning: {w}")
    return total


def _fonts(missing: set[str]) -> None:
    """Say so when the machine cannot draw some of the characters on screen."""
    if missing:
        shown = " ".join(sorted(missing)[:24])
        print(f"warning: this machine has no font for {len(missing)} character(s) on screen: {shown}\n"
              "         They will show as empty boxes. Install a font that covers them "
              "(for Korean, Japanese or Chinese: Noto Sans CJK) and run this again.")


def cmd_doctor(args) -> None:
    checks = env.doctor()
    for c in checks:
        print(f"{'ok     ' if c['ok'] else 'MISSING'}  {c['name']}: {c['detail']}")
        if c["video"]:
            print(f"         send the user this video: {c['video']}")
        if c["hint"]:
            print(f"         {c['hint']}")
    if not all(c["ok"] for c in checks):
        raise SystemExit(1)
    print("ready")


def cmd_check(args) -> None:
    from . import plan

    storyboard, root, opts, _ = _load(args)
    scenes, warnings = plan.build(storyboard, root, opts["theme"], plan.DryNarrator(), opts["captions"], opts["format"])
    _report(scenes, warnings, estimated=True)
    print("ok" if not warnings else f"ok, with {len(warnings)} warning(s)")


def _moments(scene, every_beat: bool) -> list[float]:
    """When to look at a scene: once everything in it has settled, and with --beats also just before each change."""
    stops = sorted(set(scene.stops))
    last = stops[-1] if stops else 0.0
    end = max(0.0, min(scene.duration - 0.05, max(scene.duration - 0.75, last + 1.2)))
    if not every_beat:
        return [end]
    # A little before the next change: the caption of the sentence that just ended is still up.
    return [t - (0.24 if t - prev > 1.0 else 0.04) for prev, t in zip(stops, stops[1:]) if t - prev > 0.35] + [end]


def _picked(text: str | None, count: int) -> set[int]:
    """Scene numbers from "3,7-9"; every scene when nothing is given."""
    if not text:
        return set(range(1, count + 1))
    picked: set[int] = set()
    for part in text.split(","):
        lo, _, hi = part.strip().partition("-")
        if not lo.isdigit() or (hi and not hi.isdigit()):
            raise ValueError(f'--scenes takes numbers and ranges such as "3,7-9", not {text!r}')
        picked.update(range(int(lo), int(hi or lo) + 1))
    return {n for n in picked if 1 <= n <= count}


def cmd_preview(args) -> None:
    """Frames of every scene, tiled six to a sheet: one per scene, or with --beats one per change on screen."""
    _need_tools()
    from PIL import Image, ImageDraw, ImageFont

    from . import plan, render

    storyboard, root, opts, board_path = _load(args)
    out = Path(args.out).resolve()
    work = out / ".work" / "preview"
    work.mkdir(parents=True, exist_ok=True)
    for old in work.glob("*.png"):
        old.unlink()
    scenes, warnings = plan.build(storyboard, root, opts["theme"], plan.DryNarrator(), opts["captions"], opts["format"])
    _report(scenes, warnings, estimated=True)
    wanted = _picked(args.scenes, len(scenes))
    shots: list[tuple[Path, str]] = []
    with render.Studio(opts["format"]) as studio:
        for i, scene in enumerate(scenes, 1):
            if i not in wanted:
                continue
            times = _moments(scene, args.beats)
            paths = [work / (f"{i:02d}_{k}.png" if len(times) > 1 else f"{i:02d}.png") for k in range(1, len(times) + 1)]
            studio.stills(scene, list(zip(times, paths)))
            for k, (t, path) in enumerate(zip(times, paths), 1):
                step = f"  ·  {k} of {len(times)}" if len(times) > 1 else ""
                shots.append((path, f"scene {i}{step}  ·  {t:.1f}s"))
        _fonts(studio.missing)
    name = args.name or board_path.stem
    across, (w, h) = (4, (480, 854)) if opts["format"] == "tall" else (2, (960, 540))
    per = across * (1 if opts["format"] == "tall" else 3)
    try:
        font = ImageFont.load_default(17)
    except TypeError:                                     # older Pillow: a small fixed font
        font = ImageFont.load_default()
    for n in range(0, len(shots), per):
        group = shots[n:n + per]
        sheet = Image.new("RGB", (w * across, h * ((len(group) + across - 1) // across)), "#808080")
        draw = ImageDraw.Draw(sheet)
        for j, (shot, label) in enumerate(group):
            x, y = w * (j % across), h * (j // across)
            sheet.paste(Image.open(shot).resize((w, h), Image.LANCZOS), (x, y))
            box = draw.textbbox((0, 0), label, font=font)
            draw.rectangle((x + w - box[2] - 22, y + 8, x + w - 8, y + 34), fill="#30302e")
            draw.text((x + w - box[2] - 15, y + 11), label, fill="#faf9f5", font=font)
        dest = out / f"{name}_{_tag(opts)}_preview_{n // per + 1}.png"
        sheet.save(dest)
        print(f"[preview] {dest}  ({group[0][1].split('  ·  ')[0]} to {group[-1][1].split('  ·  ')[0]})")
    print(f"[preview] full-size frames: {work}")


def cmd_render(args) -> None:
    _need_tools()
    from . import mix, plan, render
    from .tts import Narrator, VoiceUnavailable

    storyboard, root, opts, board_path = _load(args)
    out = Path(args.out).resolve()
    work = out / ".work" / (_tag(opts) + ("_silent" if args.silent else ""))
    work.mkdir(parents=True, exist_ok=True)

    t0 = time.time()
    if args.silent:                                       # no voice: captions carry the narration
        narrator, opts["captions"] = plan.DryNarrator(), True
    else:
        narrator = Narrator(opts["voice"], opts["speed"])
    try:
        scenes, warnings = plan.build(storyboard, root, opts["theme"], narrator, opts["captions"], opts["format"])
    except VoiceUnavailable as problem:
        raise Blocked(f"blocked: {problem}. Render again with --silent to make a captioned video without voice, "
                      f"and send the user this video too: {env.HELP / 'voice-model.mp4'}") from None
    total = _report(scenes, warnings, estimated=False)
    print(f"[plan] voice {'none (silent)' if args.silent else opts['voice']}, theme {opts['theme']}, {opts['format']} "
          f"({time.time() - t0:.1f}s)")

    parts = []
    with render.Studio(opts["format"]) as studio:
        for i, scene in enumerate(scenes):
            part = work / f"{i + 1:02d}_{render.scene_key(scene)}.mp4"
            if part.exists():
                print(f"[film] scene {i + 1} ({scene.payload['type']}): unchanged, reused")
            else:
                t1 = time.time()
                stats = studio.film(scene, part)
                print(f"[film] scene {i + 1} ({scene.payload['type']}): {scene.duration:.1f}s, "
                      f"{stats['captured']}/{stats['frames']} frames captured, {time.time() - t1:.1f}s")
            parts.append(part)
        _fonts(studio.missing)
    for stale in work.glob("[0-9][0-9]_*.mp4"):           # scene files from earlier versions of the storyboard
        if stale not in parts:
            stale.unlink()

    silent = work / "picture.mp4"
    render.join(parts, silent)
    voice, effects = mix.soundtrack(scenes, work)
    name = args.name or board_path.stem
    final = out / f"{name}_{_tag(opts)}.mp4"
    mix.mux(silent, voice, effects, final, storyboard.get("title", name), scenes)
    for start, title in mix.chapters(scenes):
        print(f"[chapter] {int(start // 60)}:{int(start % 60):02d}  {title}")
    print(f"[done] {final} ({int(total // 60)}:{int(total % 60):02d}, built in {time.time() - t0:.1f}s)")


def cmd_voices(args) -> None:
    from .tts import Narrator

    names = sorted(Narrator()._engine().get_voices())
    groups = {"a": "American English", "b": "British English"}
    for prefix, label in groups.items():
        for gender, word in (("f", "female"), ("m", "male")):
            print(f"{label}, {word}: " + ", ".join(v for v in names if v.startswith(prefix + gender)))


def cmd_sounds(args) -> None:
    """How the voice will pronounce each piece of text, in IPA: a way to check a word without listening."""
    from .tts import Narrator, VoiceUnavailable

    try:
        engine = Narrator()._engine()
    except VoiceUnavailable as problem:
        raise Blocked(f"blocked: {problem}") from None
    for text in args.text:
        print(f"{text}  ->  {engine.tokenizer.phonemize(text)}")


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(prog="idr", description="Don't read. Just watch.")
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p):
        p.add_argument("storyboard")
        p.add_argument("--out", default="out", help="output folder (default: ./out)")
        p.add_argument("--root", help="folder that file paths in the storyboard are relative to "
                                      "(default: the storyboard's folder)")
        p.add_argument("--theme", choices=["light", "dark"])
        p.add_argument("--format", choices=["wide", "tall"], help="wide is 1920x1080, tall is 1080x1920")
        p.add_argument("--name", help="output file name without extension")
        p.add_argument("--no-captions", dest="captions", action="store_false", default=None)

    d = sub.add_parser("doctor", help="check that this machine can render")
    d.set_defaults(func=cmd_doctor)
    c = sub.add_parser("check", help="validate a storyboard and estimate its length")
    common(c)
    c.set_defaults(func=cmd_check)
    p = sub.add_parser("preview", help="draw one frame per scene into contact sheets")
    common(p)
    p.add_argument("--beats", action="store_true", help="a frame for every change on screen (each beat and cue), "
                                                         "not only each scene's last state")
    p.add_argument("--scenes", help='only these scenes, by number as "check" lists them, e.g. "3,7-9"')
    p.set_defaults(func=cmd_preview)
    r = sub.add_parser("render", help="render a storyboard to an mp4")
    common(r)
    r.add_argument("--voice")
    r.add_argument("--speed", type=float)
    r.add_argument("--silent", action="store_true", help="no voice: time the scenes for reading and keep captions on")
    r.set_defaults(func=cmd_render)
    w = sub.add_parser("sounds", help="show how the voice will pronounce words or sentences (IPA)")
    w.add_argument("text", nargs="+")
    w.set_defaults(func=cmd_sounds)
    v = sub.add_parser("voices", help="list narration voices")
    v.set_defaults(func=cmd_voices)

    args = parser.parse_args(argv)
    try:
        args.func(args)
    except ModuleNotFoundError as problem:
        raise SystemExit(f"blocked: Python package {problem.name!r} is not installed. "
                         f"Send the user this video instead: {env.HELP / 'packages.mp4'}")
    except (ValueError, FileNotFoundError) as problem:   # includes StoryboardError and bad JSON
        raise SystemExit(f"error: {problem}")


if __name__ == "__main__":
    main(sys.argv[1:])
