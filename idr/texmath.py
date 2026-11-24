"""Math in text: find `$...$` spans the way Pandoc does, and check LaTeX with the KaTeX the player uses.

A dollar sign is not always math (prices, shell variables), so spans follow Pandoc's rule:
an opening `$` is followed by a non-space, a closing `$` is preceded by a non-space and not
followed by a digit, `\\$` is a literal dollar, and `$$...$$` is display math.
"""
from __future__ import annotations

import re
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


_COMMENT = re.compile(r"(?<!\\)%.*")
_NEWCOMMAND = re.compile(r"\\(?:re|provide)?newcommand\*?\s*\{?\s*(\\[A-Za-z@]+)\s*\}?\s*(?:\[(\d)\])?\s*(\[)?")
_DEF = re.compile(r"\\(?:g|e|x)?def\s*(\\[A-Za-z@]+)\s*((?:#\d)*)\s*(?=\{)")
_OPERATOR = re.compile(r"\\DeclareMathOperator(\*?)\s*\{?\s*(\\[A-Za-z@]+)\s*\}?\s*(?=\{)")
_INCLUDED = re.compile(r"\\(?:input|include|usepackage)\s*(?:\[[^\]]*\])?\s*\{([^{}]+)\}")
# What a macro may not expand to: KaTeX would draw these as red error text (see plan._NOT_SHOWN).
_UNSAFE = re.compile(r"\\(?:href|url|includegraphics|htmlId|htmlStyle|htmlData|htmlClass)(?![A-Za-z])")


def _group(text: str, start: int) -> tuple[str, int] | None:
    """The {...} group that opens at `start` (after any spaces): its inside, and the position just past it."""
    while start < len(text) and text[start].isspace():
        start += 1
    if start >= len(text) or text[start] != "{":
        return None
    depth, i = 0, start
    while i < len(text):
        if text[i] == "\\":
            i += 2
            continue
        depth += text[i] == "{"
        depth -= text[i] == "}"
        if depth == 0:
            return text[start + 1:i], i + 1
        i += 1
    return None


def macros(text: str) -> dict[str, str]:
    """The author's own commands defined in a LaTeX source: \\newcommand, \\renewcommand, \\def and
    \\DeclareMathOperator, as the table KaTeX takes. A paper's formulas are written with these; without them
    its equations do not parse, and with them they are shown as the author meant them.

    A command with an optional argument is left out (KaTeX has no such thing), as is one that expands to
    something a video may not show; a formula that uses it then fails the check by name."""
    text = _COMMENT.sub("", text)
    found: dict[str, str] = {}
    for m in _NEWCOMMAND.finditer(text):
        if m.group(3):                                    # [default]: an optional argument
            continue
        body = _group(text, m.end())
        if body:
            found[m.group(1)] = body[0].strip()
    for m in _DEF.finditer(text):
        body = _group(text, m.end())
        if body:
            found[m.group(1)] = body[0].strip()
    for m in _OPERATOR.finditer(text):
        body = _group(text, m.end())
        if body:
            found[m.group(2)] = f"\\operatorname{m.group(1)}{{{body[0].strip()}}}"
    return {name: body for name, body in found.items() if not _UNSAFE.search(body) and name != "\\htmlClass"}


def included(text: str) -> list[str]:
    """Files a LaTeX source pulls in (\\input, \\include, \\usepackage), which may hold its commands."""
    return [name.strip() for m in _INCLUDED.finditer(_COMMENT.sub("", text)) for name in m.group(1).split(",")]


def validate(items: list[tuple]) -> list[str | None] | None:
    """KaTeX's error for each (LaTeX, display[, macros]) item, or None where it renders. None overall if no
    browser could run."""
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
                    "items => items.map(([tex, display, macros]) => { try { katex.renderToString(tex, "
                    f"Object.assign({{ displayMode: display, macros: Object.assign({{}}, macros || {{}}) }}, {OPTIONS_JS})); "
                    "return null; } catch (e) { return String(e.message || e).replace(/^KaTeX parse error: /, ''); } })",
                    [[item[0], item[1], item[2] if len(item) > 2 else None] for item in items])
            finally:
                browser.close()
    except Exception:                                    # no browser here: the caller warns that math went unchecked
        return None
