"""Film scenes: draw each frame in headless Chrome and pipe it into ffmpeg.

One encoded file per scene, all with the same size, frame rate and encoder settings,
so they can be joined without re-encoding and a changed scene is the only one re-filmed.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from playwright.sync_api import sync_playwright

from .env import find_chrome
from .plan import FPS, Scene

WEB = Path(__file__).parent / "web"
WIDTH, HEIGHT = 1920, 1080
ENCODE = ["-c:v", "libx264", "-crf", "18", "-preset", "veryfast", "-pix_fmt", "yuv420p"]


def _player_version() -> str:
    h = hashlib.sha256()
    for name in ("player.html", "player.js", "theme.css"):
        h.update((WEB / name).read_bytes())
    return h.hexdigest()[:12]


def scene_key(scene: Scene) -> str:
    """Changes whenever the picture would: scene content, timing, or the player itself."""
    blob = json.dumps([scene.payload, scene.frames, FPS, WIDTH, HEIGHT, ENCODE, _player_version()], sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


class Studio:
    """One browser page, reused for every scene."""

    def __enter__(self):
        self._pw = sync_playwright().start()
        chrome = find_chrome()
        self._browser = self._pw.chromium.launch(executable_path=chrome, args=["--no-sandbox"])
        self.page = self._browser.new_page(viewport={"width": WIDTH, "height": HEIGHT}, device_scale_factor=1)
        self.page.goto((WEB / "player.html").as_uri())
        return self

    def __exit__(self, *exc):
        self._browser.close()
        self._pw.stop()

    def still(self, scene: Scene, t: float, path: Path) -> None:
        """Draw one frame to a PNG, for checking a layout before filming."""
        self.page.evaluate("s => window.idr.load(s)", scene.payload)
        self.page.evaluate("t => window.idr.seek(t)", t)
        self.page.screenshot(path=str(path))

    def film(self, scene: Scene, dest: Path) -> dict:
        """Encode one scene to dest. Frames that did not change are not re-captured."""
        self.page.evaluate("s => window.idr.load(s)", scene.payload)
        tmp = dest.with_name(dest.stem + ".tmp.mp4")       # a stopped render must not look finished
        ffmpeg = subprocess.Popen(
            ["ffmpeg", "-y", "-loglevel", "error", "-f", "image2pipe", "-framerate", str(FPS),
             "-c:v", "mjpeg", "-i", "-", *ENCODE, "-r", str(FPS), str(tmp)],
            stdin=subprocess.PIPE,
        )
        captured, frame = 0, b""
        for i in range(scene.frames):
            changed = self.page.evaluate("t => window.idr.seek(t)", i / FPS)
            if changed or not frame:
                frame = self.page.screenshot(type="jpeg", quality=92)
                captured += 1
            ffmpeg.stdin.write(frame)
        ffmpeg.stdin.close()
        if ffmpeg.wait() != 0:
            raise RuntimeError(f"ffmpeg failed while encoding {dest.name}")
        tmp.replace(dest)
        return {"frames": scene.frames, "captured": captured}


def join(parts: list[Path], dest: Path) -> None:
    """Concatenate scene files without re-encoding."""
    listing = dest.with_suffix(".txt")
    listing.write_text("".join(f"file '{p.resolve().as_posix()}'\n" for p in parts))
    tmp = dest.with_name(dest.stem + ".tmp.mp4")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(listing),
                    "-c", "copy", str(tmp)], check=True)
    tmp.replace(dest)
    listing.unlink()
