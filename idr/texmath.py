"""Math in text: find `$...$` spans the way Pandoc does, and check LaTeX with the KaTeX the player uses.

A dollar sign is not always math (prices, shell variables), so spans follow Pandoc's rule:
an opening `$` is followed by a non-space, a closing `$` is preceded by a non-space and not
followed by a digit, `\\$` is a literal dollar, and `$$...$$` is display math.
"""
from __future__ import annotations

from pathlib import Path

KATEX = Path(__file__).parent / "web" / "katex" / "katex.min.js"
# The same options the player renders with (see player.js): marks are drawn with \htmlClass.
OPTIONS_JS = "{ throwOnError: true, strict: 'ignore', trust: c => c.command === '\\\\htmlClass' }"

Span = tuple[int, int, str, bool]   # start, end (raw positions, delimiters included), LaTeX, display


def spans(text: str) -> list[Span]:
    """Every math span in `text`, in order."""
    out: list[Span] = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c == "\\":
            i += 2
            continue
        if c != "$":
            i += 1
            continue
        if text.startswith("$$", i):
            j = text.find("$$", i + 2)
            while j != -1 and text[j - 1] == "\\":
                j = text.find("$$", j + 2)
            if j != -1 and text[i + 2:j].strip():
                out.append((i, j + 2, text[i + 2:j].strip(), True))
                i = j + 2
                continue
            i += 2
            continue
        close = -1
        if i + 1 < n and not text[i + 1].isspace():
            j = i + 1
            while j < n:
                if text[j] == "\\":
                    j += 2
                    continue
                if text[j] == "$":
                    if not text[j - 1].isspace() and not (j + 1 < n and text[j + 1].isdigit()):
                        close = j
                    break                                # inline math never holds a bare $
                j += 1
        if close != -1:
            out.append((i, close + 1, text[i + 1:close], False))
            i = close + 1
            continue
        i += 1
    return out


def unescape(text: str) -> str:
    return text.replace("\\$", "$")


def balanced(tex: str) -> bool:
    """True when braces pair up and the piece does not end inside a command, so it can be wrapped in a group."""
    depth, i = 0, 0
    while i < len(tex):
        if tex[i] == "\\":
            if i + 1 >= len(tex):
                return False
            i += 2
            continue
        if tex[i] == "{":
            depth += 1
        elif tex[i] == "}":
            depth -= 1
            if depth < 0:
                return False
        i += 1
    return depth == 0


def validate(items: list[tuple[str, bool]]) -> list[str | None] | None:
    """KaTeX's error for each (LaTeX, display) pair, or None where it renders. None overall if no browser could run."""
    if not items:
        return []
    try:
        from playwright.sync_api import sync_playwright

        from .env import find_chrome
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=find_chrome(), args=["--no-sandbox"])
            try:
                page = browser.new_page()
                page.set_content("<!doctype html><meta charset='utf-8'><body></body>")
                page.add_script_tag(path=str(KATEX))
                return page.evaluate(
                    "items => items.map(([tex, display]) => { try { katex.renderToString(tex, "
                    f"Object.assign({{ displayMode: display }}, {OPTIONS_JS})); return null; }} "
                    "catch (e) { return String(e.message || e).replace(/^KaTeX parse error: /, ''); } })",
                    [list(item) for item in items])
            finally:
                browser.close()
    except Exception:                                    # no browser here: the caller warns that math went unchecked
        return None
