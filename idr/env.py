"""What the engine needs from the machine. Standard library only, so `doctor` runs even when nothing is installed."""
from __future__ import annotations

import importlib.util
import os
import shutil
import urllib.request
from pathlib import Path

# The v1.1 release carries a re-export of the v1.0 model that also reports phoneme durations,
# which is what lets a highlight land on a word in the middle of a sentence.
RELEASE = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.1"
MODEL = "kokoro-v1.0.onnx"   # full precision: faster on CPU than the int8 build
VOICES = "voices-v1.0.bin"
PACKAGES = {"kokoro_onnx": "kokoro-onnx", "soundfile": "soundfile", "numpy": "numpy",
            "playwright": "playwright", "pygments": "pygments", "PIL": "pillow", "pypdfium2": "pypdfium2"}
HELP = Path(__file__).parent.parent / "help"   # ready-made videos that explain each fix


def cache_dir() -> Path:
    base = os.environ.get("IDR_CACHE") or Path.home() / ".cache" / "i-dont-read"
    path = Path(base)
    path.mkdir(parents=True, exist_ok=True)
    return path


def find_chrome() -> str | None:
    """A Chrome/Chromium already on this machine, or None to use Playwright's own."""
    if os.environ.get("IDR_CHROME"):
        return os.environ["IDR_CHROME"]
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome"):
        found = shutil.which(name)
        if found:
            return found
    for path in (
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ):
        if Path(path).exists():
            return path
    return None


def playwright_chromium() -> bool:
    """Whether Playwright has downloaded its own Chromium."""
    roots = [os.environ.get("PLAYWRIGHT_BROWSERS_PATH"), Path.home() / ".cache" / "ms-playwright",
             Path.home() / "Library" / "Caches" / "ms-playwright", Path.home() / "AppData" / "Local" / "ms-playwright"]
    return any(r and Path(r).is_dir() and any(Path(r).glob("chromium*")) for r in roots)


def _voice_reachable() -> bool:
    try:
        request = urllib.request.Request(f"{RELEASE}/{VOICES}", method="HEAD")
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status < 400
    except Exception:
        return False


def doctor() -> list[dict]:
    """Check everything a render needs. Each problem names the help video that explains the fix."""
    checks = []

    def add(name: str, ok: bool, detail: str, video: str | None = None, hint: str = "") -> None:
        checks.append({"name": name, "ok": ok, "detail": detail,
                       "video": str(HELP / video) if video and not ok else None, "hint": hint if not ok else ""})

    missing = [pip for module, pip in PACKAGES.items() if importlib.util.find_spec(module) is None]
    add("python packages", not missing, "all installed" if not missing else "missing: " + ", ".join(missing),
        "packages.mp4")
    ffmpeg = shutil.which("ffmpeg")
    add("ffmpeg", bool(ffmpeg), ffmpeg or "not found on PATH", "ffmpeg.mp4")
    chrome = find_chrome()
    add("chrome", bool(chrome) or playwright_chromium(), chrome or "no Chrome, Chromium or Playwright browser found",
        "chrome.mp4")
    cached = all((cache_dir() / name).exists() for name in (MODEL, VOICES))
    reachable = cached or _voice_reachable()
    add("voice model", reachable,
        "downloaded" if cached else "not downloaded yet, but the download host is reachable" if reachable
        else "not downloaded, and the download host cannot be reached",
        "voice-model.mp4", "render with --silent to still get a captioned video")
    return checks
