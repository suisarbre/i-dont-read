"""Real pictures for image scenes: an image file, a PDF page, or a capture of a web page.

For PDFs and web pages a region can be given as text to find, and its position is looked up
in the document itself, so a box always sits on words that are really there.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

from .env import cache_dir, find_chrome

Region = list[float]   # [x, y, width, height] as fractions of the picture


def _store(key: str) -> Path:
    folder = cache_dir() / "pictures"
    folder.mkdir(exist_ok=True)
    return folder / hashlib.sha256(key.encode()).hexdigest()[:20]


def _union(rects: list[tuple[float, float, float, float]]) -> tuple[float, float, float, float]:
    return (min(r[0] for r in rects), min(r[1] for r in rects), max(r[2] for r in rects), max(r[3] for r in rects))


def _pdf(path: Path, number: int, finds: list[str]) -> dict:
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(str(path))
    if not 1 <= number <= len(doc):
        raise ValueError(f"{path.name} has {len(doc)} pages; cannot show page {number}")
    page = doc[number - 1]
    width, height = page.get_size()
    stat = path.stat()
    png = _store(f"pdf3000|{path}|{number}|{stat.st_mtime_ns}|{stat.st_size}").with_suffix(".png")
    if not png.exists():
        page.render(scale=3000 / width).to_pil().save(png)
    found: dict[str, Region | None] = {}
    text = page.get_textpage()
    for phrase in finds:
        hit = text.search(phrase, match_case=False).get_next()
        if hit is None:
            found[phrase] = None
            continue
        index, count = hit
        rects = [text.get_rect(i) for i in range(text.count_rects(index, count))]   # (left, bottom, right, top) in points
        left, bottom, right, top = _union(rects)
        found[phrase] = [left / width, 1 - top / height, (right - left) / width, (top - bottom) / height]
    return {"path": png, "found": found}


def _web(url: str, finds: list[str]) -> dict:
    """Capture a page (http(s) or a local html file) from the top, up to four screens tall."""
    from playwright.sync_api import sync_playwright

    stem = _store(f"web2x|{url}|{json.dumps(sorted(finds))}")
    png, meta = stem.with_suffix(".png"), stem.with_suffix(".json")
    fresh = png.exists() and meta.exists() and time.time() - png.stat().st_mtime < 3600
    if fresh and not url.startswith("file:"):
        return {"path": png, "found": json.loads(meta.read_text())}
    width, screen = 1440, 900
    with sync_playwright() as pw:
        proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
        browser = pw.chromium.launch(executable_path=find_chrome(), args=["--no-sandbox"],
                                     proxy={"server": proxy} if proxy and url.startswith("http") else None)
        page = browser.new_page(viewport={"width": width, "height": screen}, device_scale_factor=2)
        try:
            page.goto(url, wait_until="load", timeout=45000)
            page.wait_for_load_state("networkidle", timeout=8000)
        except Exception as problem:   # a slow tracker should not sink the capture; a page that never loads should
            if page.url in ("about:blank", "") or page.url.startswith("chrome-error:"):
                browser.close()
                raise ValueError(f"could not open {url}: {str(problem).splitlines()[0]}") from None
        height = min(4 * screen, page.evaluate("document.documentElement.scrollHeight"))
        found: dict[str, Region | None] = {}
        for phrase in finds:
            match, box = page.get_by_text(phrase, exact=False), None
            for i in range(min(match.count(), 25)):       # the first match a viewer can actually see
                hit = match.nth(i)
                if hit.is_visible():
                    box = hit.bounding_box()
                    if box and box["width"] > 0 and box["height"] > 0:
                        break
                    box = None
            found[phrase] = None if not box or box["y"] >= height else [
                box["x"] / width, box["y"] / height, box["width"] / width, min(box["height"], height - box["y"]) / height]
        page.screenshot(path=str(png), full_page=True, clip={"x": 0, "y": 0, "width": width, "height": height})
        browser.close()
    meta.write_text(json.dumps(found))
    return {"path": png, "found": found}


def resolve(root: Path, spec: dict, finds: list[str]) -> dict:
    """The picture for a scene: {"path", "iw", "ih", "label", "stamp", "found": {phrase: region or None}}."""
    from PIL import Image

    if spec.get("url"):
        url = spec["url"]
        if not url.startswith(("http://", "https://")):
            local = (root / url).resolve()
            if not local.is_file():
                raise FileNotFoundError(f"image scene points at a page that does not exist: {url}")
            label, url = spec["url"], local.as_uri()
        else:
            label = url.split("://", 1)[1].rstrip("/")
        out = _web(url, finds)
    else:
        path = (root / spec["file"]).resolve()
        if not path.is_file():
            raise FileNotFoundError(f"image scene points at a file that does not exist: {spec['file']}")
        if path.suffix.lower() == ".pdf":
            number = int(spec.get("page", 1))
            out = _pdf(path, number, finds)
            label = f"{spec['file']}  ·  page {number}"
        else:
            if finds:
                raise ValueError(f"{spec['file']}: text can only be found in PDFs and web pages; "
                                 "give the region as [x, y, width, height] fractions instead")
            out = {"path": path, "found": {}}
            label = spec["file"]
    with Image.open(out["path"]) as picture:
        out["iw"], out["ih"] = picture.size
    stat = out["path"].stat()
    out.update(label=label, stamp=f"{stat.st_mtime_ns}-{stat.st_size}")
    return out
