"""Command line: python -m idr render storyboard.json"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from . import mix, plan, render
from .tts import Narrator

CONFIG = ".i-dont-read.json"
DEFAULTS = {"theme": "light", "voice": "af_heart", "speed": 1.0}


def settings(storyboard: dict, root: Path, args) -> dict:
    """Command line beats the storyboard, which beats the project's config file, which beats defaults."""
    out = dict(DEFAULTS)
    config = root / CONFIG
    if config.is_file():
        out.update({k: v for k, v in json.loads(config.read_text()).items() if k in DEFAULTS})
    out.update({k: storyboard[k] for k in DEFAULTS if k in storyboard})
    out.update({k: getattr(args, k) for k in DEFAULTS if getattr(args, k, None) is not None})
    if out["theme"] not in ("light", "dark"):
        raise SystemExit(f"theme must be light or dark, not {out['theme']!r}")
    return out


def cmd_render(args) -> None:
    board_path = Path(args.storyboard).resolve()
    storyboard = json.loads(board_path.read_text())
    root = Path(args.root).resolve() if args.root else board_path.parent
    opts = settings(storyboard, root, args)
    out = Path(args.out).resolve()
    work = out / ".work" / opts["theme"]
    work.mkdir(parents=True, exist_ok=True)

    t0 = time.time()
    narrator = Narrator(opts["voice"], opts["speed"])
    scenes = plan.build(storyboard, root, opts["theme"], narrator)
    total = sum(s.duration for s in scenes)
    print(f"[plan] {len(scenes)} scenes, {total:.1f}s, voice {opts['voice']}, theme {opts['theme']} "
          f"({time.time() - t0:.1f}s)")

    with render.Studio() as studio:
        if args.stills:                                   # a few frames to look at before filming
            for i, scene in enumerate(scenes):
                for frac in (0.5, 0.97):
                    path = out / f"still_{opts['theme']}_{i + 1:02d}_{int(frac * 100):02d}.png"
                    studio.still(scene, scene.duration * frac, path)
                    print(f"[still] {path.name}")
            return
        parts = []
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

    silent = work / "picture.mp4"
    render.join(parts, silent)
    voice, effects = mix.soundtrack(scenes, work)
    name = args.name or board_path.stem
    final = out / f"{name}_{opts['theme']}.mp4"
    mix.mux(silent, voice, effects, final)
    print(f"[done] {final} ({total:.1f}s video, built in {time.time() - t0:.1f}s)")


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(prog="idr", description="Don't read. Just watch.")
    sub = parser.add_subparsers(dest="command", required=True)
    r = sub.add_parser("render", help="render a storyboard to an mp4")
    r.add_argument("storyboard")
    r.add_argument("--out", default="out", help="output folder (default: ./out)")
    r.add_argument("--root", help="folder that code paths in the storyboard are relative to (default: the storyboard's folder)")
    r.add_argument("--theme", choices=["light", "dark"])
    r.add_argument("--voice")
    r.add_argument("--speed", type=float)
    r.add_argument("--name", help="output file name without extension")
    r.add_argument("--stills", action="store_true", help="only draw preview frames, do not film")
    r.set_defaults(func=cmd_render)
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main(sys.argv[1:])
