"""Pull real source lines out of files and syntax-highlight them.

Code shown on screen is always read from disk by path and line range. Nothing is
retyped, so a scene cannot show code that is not in the file.
"""
from __future__ import annotations

import difflib
import html
import re
import subprocess
import unicodedata
from pathlib import Path

from pygments import lex
from pygments.lexers import TextLexer, get_lexer_for_filename
from pygments.token import Comment, Keyword, Name, Number, Operator, String
from pygments.util import ClassNotFound

from . import texmath

# Pygments token type -> theme class (see theme.css). Most specific first.
_CLASSES = [
    (Comment, "tok-comment"),
    (String, "tok-string"),
    (Number, "tok-number"),
    (Keyword, "tok-keyword"),
    (Operator.Word, "tok-keyword"),
    (Name.Function, "tok-func"),
    (Name.Class, "tok-func"),
    (Name.Decorator, "tok-func"),
    (Name.Builtin, "tok-builtin"),
    (Name.Exception, "tok-builtin"),
]

Line = list[tuple[str | None, str]]  # [(theme class or None, text), ...]


def _class_for(token_type) -> str | None:
    for parent, cls in _CLASSES:
        if token_type in parent:
            return cls
    return None


def tokenize(path: Path, text: str) -> list[Line]:
    """Lex the whole file (so multi-line strings are right) and split it into lines."""
    try:
        lexer = get_lexer_for_filename(path.name, stripnl=False, ensurenl=False)
    except ClassNotFound:
        lexer = TextLexer(stripnl=False, ensurenl=False)
    lines: list[Line] = [[]]
    for token_type, value in lex(text, lexer):
        cls = _class_for(token_type)
        for i, part in enumerate(value.split("\n")):  # a token can span lines
            if i:
                lines.append([])
            if part:
                lines[-1].append((cls, part))
    return lines


def _dedent(line: Line, cut: int) -> Line:
    out: Line = []
    for cls, text in line:
        if cut:
            drop = min(cut, len(text) - len(text.lstrip(" ")))
            text, cut = text[drop:], cut - drop
            if text:
                cut = 0
        if text:
            out.append((cls, text))
    return out


def _to_html(line: Line) -> str:
    return "".join(
        f'<span class="{cls}">{html.escape(text, quote=False)}</span>' if cls else html.escape(text, quote=False)
        for cls, text in line
    )


def _split(text: str) -> list[str]:
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return lines


def _cells(text: str) -> int:
    """Width of a line in monospace cells: wide characters (Hangul, kana, CJK, most emoji) take two."""
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in text)


def _rows(raw: list[tuple[str, int | None, int | None, Line, str]]) -> list[dict]:
    """Rows for the player: (kind, old number, new number, tokens, plain text) with shared indentation removed."""
    indents = [len(plain) - len(plain.lstrip(" ")) for *_, plain in raw if plain.strip()]
    cut = min(indents) if indents else 0
    return [{"a": str(a or ""), "b": str(b or ""), "kind": kind.strip(), "plain": plain[cut:],
             "len": _cells(plain[cut:]), "html": _to_html(_dedent(tokens, cut))}
            for kind, a, b, tokens, plain in raw]


def _decode(data: bytes, name: str, encoding: str | None = None) -> str:
    """Bytes to text without guessing: UTF-8 (or UTF-16 with a byte-order mark) unless the scene names an encoding.

    A file decoded with the wrong encoding would put text on screen that is not in the file, so this stops instead.
    Line endings are normalized, so a file saved on Windows reads the same as one saved anywhere else.
    """
    try:
        if encoding:
            text = data.decode(encoding)
        elif data[:2] in (b"\xff\xfe", b"\xfe\xff"):
            text = data.decode("utf-16")
        else:
            text = data.decode("utf-8-sig")
    except (UnicodeDecodeError, LookupError):
        raise ValueError(f'{name} is not {encoding or "UTF-8"} text. If it is in another encoding, '
                         f'name it in the scene, for example "encoding": "cp949"') from None
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _read(root: Path, file: str, ref: str | None, scene: str, encoding: str | None = None) -> str:
    """A file's text: as it is on disk, or as it was at a git ref."""
    if ref:
        text = _git_show(root, ref, file, encoding)
        if text is None:
            raise FileNotFoundError(f"{scene} scene: {file} did not exist at {ref!r}")
        return text
    path = (root / file).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"{scene} scene points at a file that does not exist: {file}")
    return _decode(path.read_bytes(), file, encoding)


def extract(root: Path, file: str, first: int, last: int, ref: str | None = None,
            encoding: str | None = None) -> list[dict]:
    """Lines first..last (1-based, inclusive) of a file, as highlighted rows. `ref` reads it at a git ref."""
    path = (root / file).resolve()
    text = _read(root, file, ref, "code", encoding).expandtabs(4)
    plain = _split(text)
    if not (1 <= first <= last <= len(plain)):
        raise ValueError(f"{file} has {len(plain)} lines; cannot show lines {first}-{last}")
    tokens = tokenize(path, text)
    return _rows([(" ", None, n, tokens[n - 1], plain[n - 1]) for n in range(first, last + 1)])


# --- diffs --------------------------------------------------------------------

def _git_show(root: Path, ref: str, file: str, encoding: str | None = None) -> str | None:
    """The file as it was at a git ref, or None if it did not exist there."""
    done = subprocess.run(["git", "-C", str(root), "show", f"{ref}:{file}"], capture_output=True)
    if done.returncode != 0:
        if b"exists on disk, but not in" in done.stderr or b"does not exist in" in done.stderr:
            return None
        raise ValueError(f"git could not read {file} at {ref!r}: {done.stderr.decode(errors='replace').strip()}")
    return _decode(done.stdout, f"{file} at {ref}", encoding)


def diff(root: Path, spec: dict, first: int, last: int) -> tuple[list[dict], str]:
    """The real change to a file between two points, around new-file lines first..last.

    Either {"file", "from": git ref, "to": git ref (default: the file on disk)}
    or {"before": path, "after": path}. Returns (rows, label for the scene).
    """
    enc = spec.get("encoding")
    if "before" in spec:
        new_path = (root / spec["after"]).resolve()
        old, new = _read(root, spec["before"], None, "diff", enc), _read(root, spec["after"], None, "diff", enc)
        label = f"{spec['before']}  →  {spec['after']}"
    else:
        file, new_path = spec["file"], (root / spec["file"]).resolve()
        old = _git_show(root, spec["from"], file, enc) or ""
        new = _read(root, file, spec.get("to"), "diff", enc)
        label = f"{file}  ·  {spec['from']} → {spec.get('to') or 'now'}"
    old, new = old.expandtabs(4), new.expandtabs(4)
    old_lines, new_lines = _split(old), _split(new)
    old_tok, new_tok = tokenize(new_path, old), tokenize(new_path, new)

    rows = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, old_lines, new_lines, autojunk=False).get_opcodes():
        if tag == "equal":
            rows += [(" ", i1 + k + 1, j1 + k + 1, new_tok[j1 + k], new_lines[j1 + k]) for k in range(i2 - i1)]
        else:
            rows += [("-", i + 1, None, old_tok[i], old_lines[i]) for i in range(i1, i2)]
            rows += [("+", None, j + 1, new_tok[j], new_lines[j]) for j in range(j1, j2)]
    inside = [i for i, r in enumerate(rows) if r[2] is not None and first <= r[2] <= last]
    if not inside:
        raise ValueError(f"the new file has {len(new_lines)} lines; cannot show lines {first}-{last}")
    lo, hi = inside[0], inside[-1]
    while lo > 0 and rows[lo - 1][0] == "-":            # removed lines belong with the lines that replaced them
        lo -= 1
    while hi + 1 < len(rows) and rows[hi + 1][0] == "-":
        hi += 1
    window = rows[lo:hi + 1]
    if all(r[0] == " " for r in window):
        raise ValueError(f"nothing changed in lines {first}-{last}; pick the lines where the change is")
    return _rows(window), label


# --- prose -------------------------------------------------------------------

def clean(text: str) -> str:
    """Light Markdown cleanup so quoted prose reads as prose. Applied to excerpts and to marks alike.

    Code spans keep their content exactly (only the backticks go): `*_ore` must not lose its
    asterisk and underscore to the emphasis rules.
    """
    text = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", text)        # images -> alt text
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)         # links -> link text
    out = []
    for part in re.split(r"(`[^`]*`)", text):
        if len(part) >= 2 and part[0] == part[-1] == "`":
            out.append(part[1:-1])
            continue
        pos = 0                                                      # math spans keep every character too
        for start, end, _, _ in texmath.spans(part):
            out.append(_unmark(part[pos:start]))
            out.append(part[start:end])
            pos = end
        out.append(_unmark(part[pos:]))
    return re.sub(r"\s+", " ", "".join(out)).strip()


def _unmark(part: str) -> str:
    part = re.sub(r"(\*\*|__)", "", part)                           # bold markers
    return re.sub(r"(?<!\w)[*_](?=\S)|(?<=\S)[*_](?!\w)", "", part)     # emphasis markers


def excerpt(root: Path, file: str, first: int, last: int, ref: str | None = None,
            encoding: str | None = None) -> list[str]:
    """Lines first..last of a text file as cleaned paragraphs (blank lines separate paragraphs)."""
    lines = _read(root, file, ref, "quote", encoding).split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    if not (1 <= first <= last <= len(lines)):
        raise ValueError(f"{file} has {len(lines)} lines; cannot quote lines {first}-{last}")
    marker = re.compile(r"^\s*(#{1,6}\s+|[-*+]\s+|\d+[.)]\s+)")       # headings and list items start a new paragraph
    paragraphs, current = [], []

    def flush() -> None:
        if current:
            paragraphs.append(clean(" ".join(current)))
            current.clear()

    for raw in lines[first - 1:last]:
        line = re.sub(r"^\s*>\s?", "", raw)                             # blockquote marker
        if not line.strip():
            flush()
            continue
        if marker.match(line):
            flush()
            line = marker.sub("", line)
        current.append(line)
    flush()
    if not paragraphs:
        raise ValueError(f"{file} lines {first}-{last} contain no text")
    return paragraphs


# --- math --------------------------------------------------------------------

_ENVS = r"equation|align|alignat|flalign|gather|multline|eqnarray"
_BLOCK = re.compile(r"\$\$(.+?)\$\$|\\\[(.+?)\\\]|(\\begin\{(" + _ENVS + r")\*?\}.*?\\end\{\4\*?\})", re.S)
_LABEL = re.compile(r"\\label\{[^{}]*\}")


def _range(root: Path, file: str, first: int, last: int, ref, encoding, scene: str) -> list[str]:
    lines = _read(root, file, ref, scene, encoding).split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    if not (1 <= first <= last <= len(lines)):
        raise ValueError(f"{file} has {len(lines)} lines; cannot show lines {first}-{last}")
    return lines[first - 1:last]


def display_math(root: Path, file: str, first: int, last: int, ref: str | None = None,
                 encoding: str | None = None) -> tuple[list[str], str]:
    """Display-math blocks that lie wholly inside lines first..last, as written, plus the first line (for `expect`).

    Blocks are $$...$$ and \\[...\\] (LaTeX or Markdown) and equation-like environments (LaTeX). The only
    change made is dropping \\label{...}, a cross-reference name that is never printed.
    """
    lines = _range(root, file, first, last, ref, encoding, "math")
    text = "\n".join(lines)
    blocks = []
    for m in _BLOCK.finditer(text):
        tex = m.group(3) or (m.group(1) if m.group(1) is not None else m.group(2))
        blocks.append(_LABEL.sub("", tex).strip())
    rest = _BLOCK.sub("", text)
    if re.search(r"\$\$|\\\[|\\begin\{(" + _ENVS + r")", rest):
        raise ValueError(f"{file} lines {first}-{last}: a math block starts in this range but ends after it; "
                         "widen the range to its end")
    if not blocks:
        raise ValueError(f'{file} lines {first}-{last} hold no display math ($$...$$, \\[...\\] or an equation '
                         'environment). If the source writes the formula as plain text, use a math scene with '
                         '"tex" instead: that is an explanation, and is shown as one')
    return blocks, lines[0]


def tex_macros(root: Path, file: str, ref: str | None = None, encoding: str | None = None) -> dict[str, str]:
    """The commands a LaTeX file defines for itself, and those in the files it pulls in from beside it."""
    from . import texmath
    if not file.lower().endswith((".tex", ".ltx", ".sty")):
        return {}
    text = _read(root, file, ref, "math", encoding)
    found: dict[str, str] = {}
    for name in texmath.included(text):                    # a paper often keeps them in macros.tex or its own .sty
        for candidate in (name, name + ".tex", name + ".sty"):
            beside = (Path(file).parent / candidate).as_posix()
            if (root / beside).is_file() and (root / beside).resolve().is_relative_to(root.resolve()):
                try:
                    found.update(texmath.macros(_read(root, beside, None, "math", encoding)))
                except (ValueError, OSError):
                    pass
                break
    found.update(texmath.macros(text))
    return found


# --- tables ------------------------------------------------------------------

_SEPARATOR = re.compile(r"^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$")


def _table_cells(line: str) -> list[str]:
    """Split one Markdown table row on pipes that are not escaped and not inside a code span."""
    body = line.strip()
    if body.startswith("|"):
        body = body[1:]
    if body.endswith("|") and not body.endswith("\\|"):
        body = body[:-1]
    cells, cur, code, i = [], "", False, 0
    while i < len(body):
        c = body[i]
        if c == "\\" and i + 1 < len(body) and body[i + 1] == "|":
            cur += "|"
            i += 2
            continue
        if c == "`":
            code = not code
        if c == "|" and not code:
            cells.append(cur)
            cur = ""
        else:
            cur += c
        i += 1
    cells.append(cur)
    return [clean(c) for c in cells]


def md_table(root: Path, file: str, first: int, last: int, ref: str | None = None,
             encoding: str | None = None) -> tuple[list[str], list[str | None], list[list[str]], str]:
    """A Markdown pipe table in lines first..last: header, column alignments, data rows, and the first line."""
    lines = _range(root, file, first, last, ref, encoding, "table")
    rows = [line for line in lines if line.strip()]
    if len(rows) < 2 or not _SEPARATOR.match(rows[1]) or "|" not in rows[0]:
        raise ValueError(f"{file} lines {first}-{last} do not start with a Markdown table (a header row, then a "
                         "row of dashes like |---|---|); start the range on the header row")
    for line in rows[2:]:
        if "|" not in line:
            raise ValueError(f"{file} lines {first}-{last}: {line.strip()[:40]!r} is not a table row; "
                             "end the range on the table's last row")
    header = _table_cells(rows[0])
    aligns = []
    for spec in _table_cells(rows[1]):
        s = spec.strip()
        aligns.append("center" if s.startswith(":") and s.endswith(":") else
                      "right" if s.endswith(":") else "left" if s.startswith(":") else None)
    data = []
    for line in rows[2:]:
        cells = _table_cells(line)
        data.append((cells + [""] * len(header))[:len(header)])
    return header, (aligns + [None] * len(header))[:len(header)], data, lines[0]


def csv_table(root: Path, file: str, first: int, last: int, columns: list | None = None, ref: str | None = None,
              encoding: str | None = None) -> tuple[list[str], list[list[str]]]:
    """Data rows first..last (1-based, after the header) of a CSV or TSV file, with chosen columns in the chosen order."""
    import csv
    import io
    text = _read(root, file, ref, "table", encoding)
    table = [row for row in csv.reader(io.StringIO(text), delimiter="\t" if file.lower().endswith(".tsv") else ",")
             if any(cell.strip() for cell in row)]
    if not table:
        raise ValueError(f"{file} is empty")
    header, body = [c.strip() for c in table[0]], table[1:]
    if not (1 <= first <= last <= len(body)):
        raise ValueError(f"{file} has {len(body)} data rows; cannot show rows {first}-{last}")
    if columns:
        pick = []
        for col in columns:
            if isinstance(col, int):
                if not 1 <= col <= len(header):
                    raise ValueError(f"{file} has {len(header)} columns; there is no column {col}")
                pick.append(col - 1)
            elif col in header:
                pick.append(header.index(col))
            else:
                raise ValueError(f"{file} has no column {col!r}; its columns are {', '.join(header)}")
    else:
        pick = list(range(len(header)))
    rows = [[(row[i] if i < len(row) else "").strip() for i in pick] for row in body[first - 1:last]]
    return [header[i] for i in pick], rows
