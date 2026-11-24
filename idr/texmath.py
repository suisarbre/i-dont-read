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


class Macros(dict):
    """The table KaTeX takes (name -> body), plus the commands it cannot take: those with an optional argument,
    as name -> (number of arguments, default for the first, body). `expand` writes those out."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.optional: dict[str, tuple[int, str, str]] = {}

    def merge(self, other: "Macros") -> None:
        for name in other:
            self.optional.pop(name, None)
        for name in other.optional:
            self.pop(name, None)
        self.update(other)
        self.optional.update(other.optional)


def _bracket(text: str, start: int) -> tuple[str, int] | None:
    """The [...] that opens at `start`: its inside and the position just past it. Brackets inside braces do not close it."""
    if start >= len(text) or text[start] != "[":
        return None
    depth, i = 0, start + 1
    while i < len(text):
        c = text[i]
        if c == "\\":
            i += 2
            continue
        depth += c == "{"
        depth -= c == "}"
        if c == "]" and depth == 0:
            return text[start + 1:i], i + 1
        i += 1
    return None


def macros(text: str) -> Macros:
    """The author's own commands defined in a LaTeX source: \\newcommand, \\renewcommand, \\def and
    \\DeclareMathOperator. A paper's formulas are written with these; without them its equations do not
    parse, and with them they are shown as the author meant them.

    A command that expands to something a video may not show is left out; a formula that uses it then fails
    the check by name."""
    text = _COMMENT.sub("", text)
    found = Macros()
    for m in _NEWCOMMAND.finditer(text):
        if m.group(3):                                    # [default]: the first argument is optional
            default = _bracket(text, m.end() - 1)
            body = _group(text, default[1]) if default else None
            if body and m.group(2):
                found.pop(m.group(1), None)
                found.optional[m.group(1)] = (int(m.group(2)), default[0], body[0].strip())
            continue
        body = _group(text, m.end())
        if body:
            found.optional.pop(m.group(1), None)
            found[m.group(1)] = body[0].strip()
    for m in _DEF.finditer(text):
        body = _group(text, m.end())
        if body:
            found[m.group(1)] = body[0].strip()
    for m in _OPERATOR.finditer(text):
        body = _group(text, m.end())
        if body:
            found[m.group(2)] = f"\\operatorname{m.group(1)}{{{body[0].strip()}}}"
    for name in [n for n, body in found.items() if _UNSAFE.search(body) or n == "\\htmlClass"]:
        del found[name]
    for name in [n for n, (_, default, body) in found.optional.items() if _UNSAFE.search(body + default)]:
        del found.optional[name]
    return found


def expand(tex: str, optional: dict[str, tuple[int, str, str]]) -> str:
    """Write out every use of a command that has an optional argument: \\half[L] becomes \\frac{L}{2}.
    KaTeX has no optional arguments, so these are expanded here, the way LaTeX would."""
    if not optional:
        return tex
    names = re.compile(r"(" + "|".join(re.escape(n) for n in sorted(optional, key=len, reverse=True)) + r")(?![A-Za-z@])")
    for _ in range(40):                                   # a body may use another such command; stop at a loop
        m = names.search(tex)
        if not m:
            return tex
        count, default, body = optional[m.group(1)]
        i = m.end()
        given = _bracket(tex, i)
        args = [given[0] if given else default]
        if given:
            i = given[1]
        for _ in range(count - 1):
            j = i
            while j < len(tex) and tex[j].isspace():
                j += 1
            group = _group(tex, j)
            if group:
                args.append(group[0])
                i = group[1]
            elif j < len(tex) and tex[j] == "\\":
                token = re.match(r"\\(?:[A-Za-z@]+|.)", tex[j:])
                args.append(token.group(0))
                i = j + token.end()
            elif j < len(tex):
                args.append(tex[j])
                i = j + 1
            else:
                args.append("")
        out = re.sub(r"#(\d)", lambda d: args[int(d.group(1)) - 1] if int(d.group(1)) <= len(args) else "", body)
        tex = f"{tex[:m.start()]}{{{out}}}{tex[i:]}"
    return tex


# --- the numbers a paper prints beside its equations ----------------------------------------------

_NUMBERED = "equation|align|alignat|flalign|gather|multline|eqnarray"
_ENV = re.compile(r"\\begin\{(" + _NUMBERED + r")(\*?)\}(.*?)\\end\{\1\2\}", re.S)
_ONE_NUMBER = ("equation", "multline")
_NO_NUMBER = re.compile(r"\\(?:nonumber|notag|tag\*?)(?![A-Za-z])")
# Anything that makes the count something other than 1, 2, 3 from the top of this file.
_OTHER_COUNT = re.compile(r"\\(?:numberwithin|setcounter\s*\{equation\}|addtocounter\s*\{equation\}|theequation|"
                          r"begin\{subequations\}|appendix(?![A-Za-z])|(?:re)?newenvironment|eqno|leqno|"
                          r"documentclass(?:\[[^\]]*\])?\{(?:book|report|memoir|amsbook|scrbook|scrreprt)\})")


def _blank_comments(text: str) -> str:
    return _COMMENT.sub(lambda m: " " * len(m.group(0)), text)


def _row_ends(body: str) -> list[int]:
    """Where each row of an environment's body ends: before every top-level \\\\, and at the end."""
    ends, depth, nested, i = [], 0, 0, 0
    while i < len(body):
        if body.startswith("\\begin{", i):
            nested += 1
        elif body.startswith("\\end{", i):
            nested -= 1
        if body[i] == "\\":
            if body.startswith("\\\\", i) and depth == 0 and nested == 0:
                ends.append(i)
            i += 2
            continue
        depth += body[i] == "{"
        depth -= body[i] == "}"
        i += 1
    ends.append(len(body))
    return ends


def _takes_number(env: str, star: str, body: str) -> list[bool] | None:
    """For each row, whether LaTeX numbers it; None when that cannot be told from the text."""
    if star:
        return []
    if env in _ONE_NUMBER:
        return [not _NO_NUMBER.search(body)]
    rows, start = [], 0
    for end in _row_ends(body):
        rows.append(body[start:end])
        start = end + 2
    if len(rows) > 1 and not rows[-1].strip():
        return None                                       # a trailing \\ makes LaTeX number an empty row; packages differ
    return [not _NO_NUMBER.search(row) for row in rows]


def equation_numbers(text: str, start: int, defined: dict | None = None) -> list[int | None] | None | bool:
    """The numbers LaTeX prints beside the numbered environment that begins at `start` in the file `text`.

    A list with one entry per row (None for a row with no number); False when the block is not one LaTeX
    numbers (so there is nothing to do); None when the numbers cannot be told from this file alone: the paper
    counts by section, sets the counter, pulls in other files first, or wraps equations in its own commands.
    A wrong number is a false label on the source, so the caller then shows none."""
    clean = _blank_comments(text)
    here = _ENV.match(clean, start)
    if not here or here.group(2):
        return False
    doc = clean.find("\\begin{document}")
    if doc == -1 or doc > start or _OTHER_COUNT.search(clean):
        return None
    if _ENV.search(clean[:doc]) or re.search(r"\\(?:input|include)\s*\{", clean[doc:start]):
        return None
    if any("\\begin{" in body or "\\end{" in body for body in (defined or {}).values()):
        return None
    count = 0
    for m in _ENV.finditer(clean, doc, start):
        rows = _takes_number(*m.groups())
        if rows is None:
            return None
        count += sum(rows)
    rows = _takes_number(*here.groups())
    if rows is None:
        return None
    out = []
    for numbered in rows:
        count += numbered
        out.append(count if numbered else None)
    return out


def renumbered(tex: str, numbers: list[int | None] | None) -> str:
    """A numbered environment with the paper's own numbers written in as tags (KaTeX would count from 1 in
    every scene), or with no numbers when they are not known."""
    m = re.match(r"\\begin\{(" + _NUMBERED + r")\}(.*)\\end\{\1\}\s*$", tex, re.S)
    if not m:
        return tex
    env, body = m.groups()
    if numbers:
        ends = [len(body.rstrip())] if env in _ONE_NUMBER else _row_ends(body)
        for end, number in reversed(list(zip(ends, numbers))):
            if number is not None:
                body = f"{body[:end]} \\tag{{{number}}} {body[end:]}"
    return f"\\begin{{{env}*}}{body}\\end{{{env}*}}"


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
