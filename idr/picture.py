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

Region = list[list[float]]   # one or more [x, y, width, height] boxes, as fractions of the picture (one per line of text)


def _store(key: str) -> Path:
    folder = cache_dir() / "pictures"
    folder.mkdir(exist_ok=True)
    return folder / hashlib.sha256(key.encode()).hexdigest()[:20]


def _by_line(rects: list[tuple[float, float, float, float]]) -> list[tuple[float, float, float, float]]:
    """Join the pieces of a match that sit on the same line (justified text gives one piece per word)."""
    lines: list[list[float]] = []
    for left, bottom, right, top in sorted(rects, key=lambda r: (-r[3], r[0])):
        middle = (bottom + top) / 2
        if lines and lines[-1][1] <= middle <= lines[-1][3]:
            last = lines[-1]
            last[0], last[1], last[2], last[3] = min(last[0], left), min(last[1], bottom), max(last[2], right), max(last[3], top)
        else:
            lines.append([left, bottom, right, top])
    return [tuple(line) for line in lines]


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
        # One rectangle per line the phrase runs over, as (left, bottom, right, top) in points.
        rects = [text.get_rect(i) for i in range(text.count_rects(index, count))]
        found[phrase] = [[left / width, 1 - top / height, (right - left) / width, (top - bottom) / height]
                         for left, bottom, right, top in _by_line(rects)]
    return {"path": png, "found": found}


# Runs in the page. Finds each phrase in the text a reader can see and returns, per phrase, one
# rectangle per line of the match (page coordinates), whether something else is drawn over it, and
# why a phrase could not be used. Also reports what sits fixed over the first screen (consent
# dialogs, banners) and pictures that did not load.
_LOOK = r"""
async ({ phrases, top, height, screen }) => {
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const SKIP = new Set(['SCRIPT', 'STYLE', 'NOSCRIPT', 'TEMPLATE', 'TITLE', 'HEAD']);
  const blocks = new WeakMap();
  const blockOf = el => {
    if (blocks.has(el)) return blocks.get(el);
    let b = el;
    while (b.parentElement && getComputedStyle(b).display.startsWith('inline')) b = b.parentElement;
    blocks.set(el, b);
    return b;
  };
  // The visible text of the page as one string with single spaces, and where each character came from.
  let text = '';
  const from = [];
  const push = (ch, node, offset) => {
    if (/\s/.test(ch)) { if (text.endsWith(' ') || !text) return; ch = ' '; }
    text += ch; from.push(node ? [node, offset] : null);
  };
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  let lastBlock = null;
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    const p = n.parentElement;
    if (!p || SKIP.has(p.tagName)) continue;
    if (p.checkVisibility && !p.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true })) continue;
    const block = blockOf(p);
    if (block !== lastBlock) push(' ', null, 0);            // words in different blocks never run together
    lastBlock = block;
    for (let i = 0; i < n.data.length; i++) push(n.data[i], n, i);
  }
  const lower = text.toLowerCase();
  const pinned = el => {                                     // inside something fixed or sticky?
    for (let e = el; e && e !== document.documentElement; e = e.parentElement) {
      const pos = getComputedStyle(e).position;
      if (pos === 'fixed' || pos === 'sticky') return e;
    }
    return null;
  };
  const say = el => (el.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 70);
  const byLine = rects => {
    const lines = [];
    for (const r of rects.sort((a, b) => a.y - b.y || a.x - b.x)) {
      const last = lines[lines.length - 1];
      const mid = r.y + r.h / 2;
      if (last && mid > last.y && mid < last.y + last.h) {
        const x1 = Math.max(last.x + last.w, r.x + r.w), y1 = Math.max(last.y + last.h, r.y + r.h);
        last.x = Math.min(last.x, r.x); last.y = Math.min(last.y, r.y); last.w = x1 - last.x; last.h = y1 - last.y;
      } else lines.push({ ...r });
    }
    return lines;
  };
  const locate = (phrase, bounded) => {
    const needle = phrase.replace(/\s+/g, ' ').trim();
    let outside = null;
    for (const hay of [text, lower.length === text.length ? lower : null]) {
      if (!hay) continue;
      const want = hay === text ? needle : needle.toLowerCase();
      for (let i = hay.indexOf(want), tries = 0; i >= 0 && tries < 40; i = hay.indexOf(want, i + 1), tries++) {
        let a = i, b = i + want.length - 1;
        while (a <= b && !from[a]) a++;
        while (b >= a && !from[b]) b--;
        if (a > b) continue;
        const range = document.createRange();
        range.setStart(from[a][0], from[a][1]);
        range.setEnd(from[b][0], from[b][1] + 1);
        const rects = byLine([...range.getClientRects()].filter(r => r.width > 1 && r.height > 1)
          .map(r => ({ x: r.left + scrollX, y: r.top + scrollY, w: r.width, h: r.height })));
        if (!rects.length) continue;
        const y0 = rects[0].y, y1 = rects[rects.length - 1].y + rects[rects.length - 1].h;
        if (bounded && (y0 < top || y1 > top + height)) { outside = outside || (y0 < top ? 'above' : 'below'); continue; }
        return { rects, range };
      }
      if (outside) break;
    }
    return { why: outside || 'missing' };
  };
  const found = {};
  for (const phrase of phrases) {
    const hit = locate(phrase, true);
    if (!hit.rects) { found[phrase] = { why: hit.why }; continue; }
    // Is something else drawn over these words in the capture? Fixed things are painted over the first screen only.
    const first = hit.rects[0];
    const anchor = hit.range.commonAncestorContainer.nodeType === 1 ? hit.range.commonAncestorContainer
                                                                   : hit.range.commonAncestorContainer.parentElement;
    const firstScreen = first.y + first.h / 2 < top + screen;
    scrollTo(0, firstScreen ? top : Math.max(0, first.y - screen / 2));
    await sleep(30);
    const over = document.elementFromPoint(first.x + first.w / 2 - scrollX, first.y + first.h / 2 - scrollY);
    let covered = null;
    if (over && !anchor.contains(over) && !over.contains(anchor) && (firstScreen || !pinned(over))) {
      const root = pinned(over) || over;
      covered = say(root) || say(over) || 'a layer with no text';
    }
    const br = blockOf(anchor).getBoundingClientRect();     // the paragraph (or figure, or cell) the words sit in
    found[phrase] = { rects: hit.rects.map(r => [r.x, r.y - top, r.w, r.h]), covered, block: [br.left + scrollX, br.width] };
  }
  // What is fixed over the first screen of the capture?
  scrollTo(0, top);
  await sleep(60);
  const roots = new Map();
  let hits = 0, points = 0;
  for (let gy = 1; gy <= 5; gy++) for (let gx = 1; gx <= 7; gx++) {
    points++;
    const el = document.elementFromPoint(innerWidth * gx / 8, innerHeight * gy / 6);
    const root = el && pinned(el);
    if (!root || getComputedStyle(root).position !== 'fixed') continue;
    hits++; roots.set(root, (roots.get(root) || 0) + 1);
  }
  let overlay = null;
  if (hits / points >= 0.2) {
    const all = [...document.querySelectorAll('*')].filter(e => getComputedStyle(e).position === 'fixed'
      && e.getBoundingClientRect().width > 0 && (!e.checkVisibility || e.checkVisibility()));
    const words = all.map(say).filter(Boolean).sort((a, b) => b.length - a.length)[0] || '';
    const buttons = [...new Set(all.flatMap(e => [...e.querySelectorAll('button, [role=button], input[type=button], input[type=submit], a')])
      .map(b => (b.innerText || b.value || '').replace(/\s+/g, ' ').trim()).filter(t => t && t.length <= 40))].slice(0, 6);
    overlay = { share: Math.round(100 * hits / points), words, buttons };
  }
  // Smaller fixed boxes (a newsletter prompt, a chat bubble): painted over the first screen too.
  const floats = overlay ? [] : [...document.querySelectorAll('*')].filter(e => getComputedStyle(e).position === 'fixed'
      && (!e.checkVisibility || e.checkVisibility())).map(e => ({ e, r: e.getBoundingClientRect() }))
    .filter(({ r }) => r.width * r.height > 0.015 * innerWidth * innerHeight && !(r.top < 8 && r.width > 0.8 * innerWidth)
      && r.bottom > 0 && r.top < innerHeight)
    .map(({ e, r }) => ({ words: say(e), rect: [r.left, r.top, r.width, r.height],
                          where: `${r.top + r.height / 2 < innerHeight / 2 ? 'top' : 'bottom'} ${r.left + r.width / 2 < innerWidth / 2 ? 'left' : 'right'}` }))
    .slice(0, 3);
  const broken = [...document.images].filter(i => i.complete && i.naturalWidth === 0 && i.getAttribute('src')).filter(i => {
    const r = i.getBoundingClientRect();
    return r.width > 0 && r.bottom + scrollY > top && r.top + scrollY < top + height;
  }).map(i => {
    const r = i.getBoundingClientRect();
    let host = 'this page';
    try { host = new URL(i.currentSrc || i.src, location.href).host || host; } catch (e) {}
    return { host, rect: [r.left + scrollX, r.top + scrollY - top, Math.max(r.width, 16), Math.max(r.height, 16)] };
  });
  return { found, overlay, floats, broken };
}
"""


def _web(url: str, finds: list[str], clicks: list[str], start: str | None) -> dict:
    """Capture a page (http(s) or a local html file) as a reader would see it, up to four screens tall.

    Before the picture is taken the page is scrolled through once, so parts that load only when they
    come into view are there. `clicks` are things to press first (a consent button, a tab), by the words
    on them. `start` is a phrase on the page: the capture begins just above it instead of at the top.
    """
    from playwright.sync_api import sync_playwright

    stem = _store(f"web7|{url}|{json.dumps(sorted(finds))}|{json.dumps(clicks)}|{start}")
    png, meta = stem.with_suffix(".png"), stem.with_suffix(".json")
    fresh = png.exists() and meta.exists() and time.time() - png.stat().st_mtime < 3600
    if fresh and not url.startswith("file:"):
        return {"path": png, **json.loads(meta.read_text())}
    width, screen = 1440, 900
    notes: list[str] = []
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
        for words in clicks:
            target = None
            for candidates in (page.get_by_role("button", name=words, exact=True), page.get_by_role("link", name=words, exact=True),
                               page.get_by_role("tab", name=words, exact=True), page.get_by_text(words, exact=True)):
                for i in range(min(candidates.count(), 10)):
                    if candidates.nth(i).is_visible():
                        target = candidates.nth(i)
                        break
                if target:
                    break
            if target is None:
                notes.append(f'"click": nothing visible on the page reads {words!r}, so nothing was pressed')
                continue
            try:
                target.click(timeout=4000)
                page.wait_for_timeout(500)
            except Exception as problem:
                notes.append(f'"click": could not press {words!r} ({str(problem).splitlines()[0]})')
        # Walk down the page once, the way a reader scrolls, so lazy parts load; then go back up.
        page.evaluate("scrollTo(0, 0)")
        for _ in range(40):
            page.mouse.wheel(0, int(screen * 0.8))
            page.wait_for_timeout(180)
            if page.evaluate("scrollY + innerHeight >= document.documentElement.scrollHeight - 2"):
                break
        page.wait_for_timeout(700)
        try:
            page.wait_for_load_state("networkidle", timeout=4000)
        except Exception:
            pass
        top = 0.0
        if start:
            at = page.evaluate(_LOOK, {"phrases": [start], "top": 0, "height": 10 ** 9, "screen": screen})["found"][start]
            if not at.get("rects"):
                browser.close()
                raise ValueError(f'"top": the words {start!r} are not on the page {url}')
            top = float(max(0, int(at["rects"][0][1]) - 96))
        full = page.evaluate("document.documentElement.scrollHeight")
        top = min(top, max(0.0, full - screen))
        height = min(4 * screen, full - top)
        look = page.evaluate(_LOOK, {"phrases": finds, "top": top, "height": height, "screen": screen})
        page.evaluate("y => scrollTo(0, y)", top)
        page.wait_for_timeout(250)
        page.screenshot(path=str(png), full_page=True, clip={"x": 0, "y": top, "width": width, "height": height})
        browser.close()

    found: dict[str, Region | None] = {}
    why: dict[str, str] = {}
    blocks: dict[str, list[float]] = {}
    for phrase, hit in look["found"].items():
        if not hit.get("rects"):
            found[phrase], why[phrase] = None, hit["why"]
            continue
        found[phrase] = [[x / width, y / height, w / width, h / height] for x, y, w, h in hit["rects"]]
        blocks[phrase] = [max(0.0, hit["block"][0] / width), min(1.0, hit["block"][1] / width)]
        if hit.get("covered"):
            notes.append(f"the words {phrase!r} are covered by something else on the page ({hit['covered']})")
    if look["overlay"]:
        o = look["overlay"]
        press = (' Its buttons read: ' + ", ".join(repr(t) for t in o["buttons"]) + '. To close it the way a reader would, '
                 'add "click": ["the button"] to the scene.') if o["buttons"] else ""
        notes.append(f"something fixed in place covers about {o['share']}% of the first screen of the capture"
                     + (f" ({o['words']!r})" if o["words"] else "") + "." + press)
    frac = lambda r: [r[0] / width, r[1] / height, r[2] / width, r[3] / height]
    # Things to keep out of the frame: reported only for the scenes whose camera actually shows them.
    avoid = [{"rect": frac(box["rect"]), "what": f"a box fixed in place over the page ({box['words']!r})",
              "fix": 'frame it out with "zoom", or close it with "click" if it has a button'} for box in look["floats"]]
    avoid += [{"rect": frac(img["rect"]), "what": f"a picture that did not load (from {img['host']})",
               "fix": 'frame it out with "zoom"'} for img in look["broken"]]
    out = {"found": found, "why": why, "notes": notes, "avoid": avoid, "blocks": blocks}
    meta.write_text(json.dumps(out))
    return {"path": png, **out}


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
        clicks = spec.get("click") or []
        out = _web(url, finds, [clicks] if isinstance(clicks, str) else list(clicks), spec.get("top"))
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
    # The stamp is the picture's content, not its timestamp: a page captured again with the same
    # result must not make its scene look changed.
    out.update(label=label, stamp=hashlib.sha256(out["path"].read_bytes()).hexdigest()[:16])
    return out
