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
DEFAULTS = {"theme": "light", "voice": "af_heart", "speed": 1.0, "captions": True}


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
    return out


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
    scenes, warnings = plan.build(storyboard, root, opts["theme"], plan.DryNarrator(), opts["captions"])
    _report(scenes, warnings, estimated=True)
    print("ok" if not warnings else f"ok, with {len(warnings)} warning(s)")


def cmd_preview(args) -> None:
    """One frame per scene, at the moment the most is on screen, tiled six to a sheet."""
    _need_tools()
    from PIL import Image

    from . import plan, render

    storyboard, root, opts, board_path = _load(args)
    out = Path(args.out).resolve()
    work = out / ".work" / "preview"
    work.mkdir(parents=True, exist_ok=True)
    scenes, warnings = plan.build(storyboard, root, opts["theme"], plan.DryNarrator(), opts["captions"])
    _report(scenes, warnings, estimated=True)
    shots = []
    with render.Studio() as studio:
        for i, scene in enumerate(scenes):
            path = work / f"{i + 1:02d}.png"
            studio.still(scene, max(0.0, scene.duration - 0.75), path)
            shots.append(path)
    name = args.name or board_path.stem
    for n in range(0, len(shots), 6):
        group = shots[n:n + 6]
        sheet = Image.new("RGB", (1920, 540 * ((len(group) + 1) // 2)), "#808080")
        for j, shot in enumerate(group):
            sheet.paste(Image.open(shot).resize((960, 540), Image.LANCZOS), (960 * (j % 2), 540 * (j // 2)))
        dest = out / f"{name}_{opts['theme']}_preview_{n // 6 + 1}.png"
        sheet.save(dest)
        print(f"[preview] {dest}  (scenes {n + 1}-{n + len(group)})")


def cmd_render(args) -> None:
    _need_tools()
    from . import mix, plan, render
    from .tts import Narrator, VoiceUnavailable

    storyboard, root, opts, board_path = _load(args)
    out = Path(args.out).resolve()
    work = out / ".work" / (opts["theme"] + ("_silent" if args.silent else ""))
    work.mkdir(parents=True, exist_ok=True)

    t0 = time.time()
    if args.silent:                                       # no voice: captions carry the narration
        narrator, opts["captions"] = plan.DryNarrator(), True
    else:
        narrator = Narrator(opts["voice"], opts["speed"])
    try:
        scenes, warnings = plan.build(storyboard, root, opts["theme"], narrator, opts["captions"])
    except VoiceUnavailable as problem:
        raise Blocked(f"blocked: {problem}. Render again with --silent to make a captioned video without voice, "
                      f"and send the user this video too: {env.HELP / 'voice-model.mp4'}") from None
    total = _report(scenes, warnings, estimated=False)
    print(f"[plan] voice {'none (silent)' if args.silent else opts['voice']}, theme {opts['theme']} "
          f"({time.time() - t0:.1f}s)")

    parts = []
    with render.Studio() as studio:
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
    for stale in work.glob("[0-9][0-9]_*.mp4"):           # scene files from earlier versions of the storyboard
        if stale not in parts:
            stale.unlink()

    silent = work / "picture.mp4"
    render.join(parts, silent)
    voice, effects = mix.soundtrack(scenes, work)
    name = args.name or board_path.stem
    final = out / f"{name}_{opts['theme']}.mp4"
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


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(prog="idr", description="Don't read. Just watch.")
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p):
        p.add_argument("storyboard")
        p.add_argument("--out", default="out", help="output folder (default: ./out)")
        p.add_argument("--root", help="folder that file paths in the storyboard are relative to "
                                      "(default: the storyboard's folder)")
        p.add_argument("--theme", choices=["light", "dark"])
        p.add_argument("--name", help="output file name without extension")
        p.add_argument("--no-captions", dest="captions", action="store_false", default=None)

    d = sub.add_parser("doctor", help="check that this machine can render")
    d.set_defaults(func=cmd_doctor)
    c = sub.add_parser("check", help="validate a storyboard and estimate its length")
    common(c)
    c.set_defaults(func=cmd_check)
    p = sub.add_parser("preview", help="draw one frame per scene into contact sheets")
    common(p)
    p.set_defaults(func=cmd_preview)
    r = sub.add_parser("render", help="render a storyboard to an mp4")
    common(r)
    r.add_argument("--voice")
    r.add_argument("--speed", type=float)
    r.add_argument("--silent", action="store_true", help="no voice: time the scenes for reading and keep captions on")
    r.set_defaults(func=cmd_render)
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
