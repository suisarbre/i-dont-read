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
    if "\x00" in text:                                   # UTF-16 with no byte-order mark reads as UTF-8 full of NULs
        raise ValueError(f"{name} holds NUL characters, so it is not {encoding or 'UTF-8'} text. If it is UTF-16, "
                         'name it in the scene: "encoding": "utf-16-le"')
    return text.replace("\r\n", "\n").replace("\r", "\n")


def inside(root: Path, file: str, scene: str) -> Path:
    """The path of a file of the source. A scene shows the source, so a path that leaves its folder (through
    "..", an absolute path, or a link that points out of it) is refused: that file is not part of what the
    video says it shows."""
    if not isinstance(file, str) or not file.strip():
        raise ValueError(f'{scene} scene: "file" is the path of a file in the source, not {file!r}')
    path = (root / file).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError(f"{scene} scene: {file} is outside the source folder ({root}). A scene shows files of the "
                         "source: copy the file into that folder, or pass the folder that holds both as --root")
    return path


def _read(root: Path, file: str, ref: str | None, scene: str, encoding: str | None = None) -> str:
    """A file's text: as it is on disk, or as it was at a git ref."""
    path = inside(root, file, scene)
    if ref:
        text = _git_show(root, ref, file, encoding)
        if text is None:
            raise FileNotFoundError(f"{scene} scene: {file} did not exist at {ref!r}")
        return text
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
    # A ref is a commit, branch or tag name. Anything that git could take for an option is refused before git sees it.
    if not isinstance(ref, str) or not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_./@^~{}-]*", ref) or ".." in ref:
        raise ValueError(f"{ref!r} is not a git ref; give a commit, a branch or a tag, such as \"HEAD~1\" or \"v1.2\"")
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
                 encoding: str | None = None, defined: dict | None = None) -> tuple[list[str], str, list]:
    """Display-math blocks that lie wholly inside lines first..last, as written, plus the first line (for `expect`)
    and, for each block, the equation numbers the paper prints beside it (see texmath.equation_numbers).

    Blocks are $$...$$ and \\[...\\] (LaTeX or Markdown) and equation-like environments (LaTeX). The only
    change made is dropping \\label{...}, a cross-reference name that is never printed.
    """
    from . import texmath
    lines = _range(root, file, first, last, ref, encoding, "math")
    text = "\n".join(lines)
    whole = _read(root, file, ref, "math", encoding)
    offset = sum(len(line) + 1 for line in whole.split("\n")[:first - 1])
    blocks, numbers = [], []
    for m in _BLOCK.finditer(text):
        tex = m.group(3) or (m.group(1) if m.group(1) is not None else m.group(2))
        blocks.append(_LABEL.sub("", tex).strip())
        numbers.append(texmath.equation_numbers(whole, offset + m.start(), defined) if m.group(3) else False)
    rest = _BLOCK.sub("", text)
    if re.search(r"\$\$|\\\[|\\begin\{(" + _ENVS + r")", rest):
        raise ValueError(f"{file} lines {first}-{last}: a math block starts in this range but ends after it; "
                         "widen the range to its end")
    if not blocks:
        raise ValueError(f'{file} lines {first}-{last} hold no display math ($$...$$, \\[...\\] or an equation '
                         'environment). If the source writes the formula as plain text, use a math scene with '
                         '"tex" instead: that is an explanation, and is shown as one')
    return blocks, lines[0], numbers


def tex_macros(root: Path, file: str, ref: str | None = None, encoding: str | None = None):
    """The commands a LaTeX file defines for itself, and those in the files it pulls in from beside it."""
    from . import texmath
    found = texmath.Macros()
    if not file.lower().endswith((".tex", ".ltx", ".sty")):
        return found
    text = _read(root, file, ref, "math", encoding)
    for name in texmath.included(text):                    # a paper often keeps them in macros.tex or its own .sty
        for candidate in (name, name + ".tex", name + ".sty"):
            beside = (Path(file).parent / candidate).as_posix()
            if (root / beside).is_file() and (root / beside).resolve().is_relative_to(root.resolve()):
                try:
                    found.merge(texmath.macros(_read(root, beside, None, "math", encoding)))
                except (ValueError, OSError):
                    pass
                break
    found.merge(texmath.macros(text))
    for name in list(found):                               # a plain command may be written with an optional-argument one
        found[name] = texmath.expand(found[name], found.optional)
    return found


# --- LaTeX tables ------------------------------------------------------------

_TABULAR = re.compile(r"\\begin\{(tabular\*?|tabularx|longtable|array)\}(.*?)\\end\{\1\}", re.S)
_RULES = re.compile(r"\\(?:hline|toprule|midrule|bottomrule|endhead|endfirsthead|endfoot|endlastfoot|addlinespace)(?![A-Za-z])"
                    r"(?:\[[^\]]*\])?|\\(?:cline|cmidrule)(?:\([^)]*\))?\{[^{}]*\}")
_PLAIN_COMMANDS = re.compile(r"\\(?:textbf|textit|emph|textrm|textsf|texttt|textsc|mathrm|text|mbox|underline)\s*\{([^{}]*)\}")


def _outside_math(text: str, change) -> str:
    """Apply `change` to the parts of a cell that are not $...$ math."""
    from . import texmath
    out, pos = [], 0
    for start, end, _, _ in texmath.spans(text):
        out.append(change(text[pos:start]))
        out.append(text[start:end])
        pos = end
    out.append(change(text[pos:]))
    return "".join(out)


def _tex_cell(cell: str, where: str) -> str:
    def plain(text: str) -> str:
        for _ in range(4):
            text = _PLAIN_COMMANDS.sub(r"\1", text)
        text = re.sub(r"\\([%&_#{}])", r"\1", text).replace("~", " ").replace("---", "—").replace("--", "–")
        text = re.sub(r"\\[,;! ]", " ", text)
        left = re.search(r"\\[A-Za-z]+", text)
        if left:
            raise ValueError(f"{where}: a cell uses {left.group(0)}, which a table scene cannot show as the paper "
                             'prints it; write the table out with "header" and "rows", and name the paper in "source"')
        return text.replace("{", "").replace("}", "")
    cell = " ".join(_outside_math(cell.strip(), plain).split())
    number = re.fullmatch(r"\$\s*([-+]?)\s*(\d[\d,]*(?:\.\d+)?)\s*\$", cell)
    if number:                                             # $-0.8$ is how LaTeX writes a minus sign: the same number, as text
        return ("−" if number.group(1) == "-" else number.group(1)) + number.group(2)
    return cell


def _split_top(text: str, sep: str) -> list[str]:
    """Split on `sep` where it is not inside braces or $...$."""
    parts, cur, depth, math, i = [], "", 0, False, 0
    while i < len(text):
        c = text[i]
        if c == "\\" and not text.startswith(sep, i):
            cur += text[i:i + 2]
            i += 2
            continue
        if c == "$":
            math = not math
        depth += c == "{"
        depth -= c == "}"
        if text.startswith(sep, i) and depth == 0 and not math:
            parts.append(cur)
            cur = ""
            i += len(sep)
            continue
        cur += c
        i += 1
    parts.append(cur)
    return parts


def tex_table(root: Path, file: str, first: int, last: int, ref: str | None = None,
              encoding: str | None = None) -> tuple[list[str], list[str | None], list[list[str]], str]:
    """The LaTeX table (a tabular) inside lines first..last: header, column alignments, data rows, and the first line."""
    from . import texmath
    lines = _range(root, file, first, last, ref, encoding, "table")
    where = f"{file} lines {first}-{last}"
    text = "\n".join(texmath._COMMENT.sub("", line) for line in lines)
    found = _TABULAR.findall(text)
    if len(found) != 1:
        raise ValueError(f"{where} hold {len(found) or 'no'} LaTeX table{'s' if len(found) > 1 else ''} "
                         "(\\begin{tabular} ... \\end{tabular}); the range must take in exactly one, from its "
                         "\\begin line to its \\end line")
    env, body = found[0]
    if env.startswith("tabular*") or env == "tabularx":   # {width}{columns}
        body = body[texmath._group(body, 0)[1]:] if texmath._group(body, 0) else body
    option = re.match(r"\s*\[[^\]]*\]", body)
    if option:
        body = body[option.end():]
    cols = texmath._group(body, 0)
    if not cols:
        raise ValueError(f"{where}: the table has no column list after \\begin{{{env}}}")
    spec = re.sub(r"[@!<>]\{[^{}]*\}|\|", "", cols[0])
    spec = re.sub(r"[pmbX]\{[^{}]*\}", "l", spec).replace("X", "l")
    aligns = [{"l": None, "c": "center", "r": "right"}.get(c) for c in spec if c in "lcr"]
    body = body[cols[1]:]
    if re.search(r"\\(?:multicolumn|multirow)(?![A-Za-z])", body):
        raise ValueError(f"{where}: the table has cells that span columns or rows (\\multicolumn, \\multirow), which "
                         'a table scene does not draw; write it out with "header" and "rows", and name the paper in "source"')
    body = _RULES.sub("", body)
    rows = []
    for raw in _split_top(body, "\\\\"):
        raw = re.sub(r"^\s*\[[^\]]*\]", "", raw)              # \\[2pt]: extra space after the row above
        if not raw.strip():
            continue
        rows.append([_tex_cell(cell, where) for cell in _split_top(raw, "&")])
    if len(rows) < 2:
        raise ValueError(f"{where}: the table has no rows under its first one")
    width = len(rows[0])
    for n, row in enumerate(rows[1:], 1):
        if len(row) != width:
            raise ValueError(f"{where}: row {n} has {len(row)} cells but the first row has {width}")
    return rows[0], (aligns + [None] * width)[:width], rows[1:], lines[0]


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
    return [_cell(c) for c in cells]


def _cell(raw: str) -> str:
    """One table cell as text. A star or dagger after the content is a footnote mark, not emphasis, and stays:
    "12*" in a table means "12, but read the note"."""
    mark = re.fullmatch(r"(\s*[^*\s][^*]*?)((?:\\?\*){1,3}|[†‡§])\s*", raw)
    if mark:
        return clean(mark.group(1)) + mark.group(2).replace("\\", "")
    return clean(raw)


def md_table(root: Path, file: str, first: int, last: int, ref: str | None = None,
             encoding: str | None = None) -> tuple[list[str], list[str | None], list[list[str]], str]:
    """A Markdown pipe table in lines first..last: header, column alignments, data rows, and the first line."""
    lines = _range(root, file, first, last, ref, encoding, "table")
    rows = [line for line in lines if line.strip()]
    if len(rows) < 2 or not _SEPARATOR.match(rows[1]) or "|" not in rows[0]:
        raise ValueError(f"{file} lines {first}-{last} do not start with a Markdown table (a header row, then a "
                         "row of dashes like |---|---|); start the range on the header row. If the table is not "
                         'written that way in the source, write it out with "header" and "rows", and name the '
                         'source in "source"')
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
        if len(cells) > len(header) and any(c.strip() for c in cells[len(header):]):
            raise ValueError(f"{file} lines {first}-{last}: the row {line.strip()[:40]!r} has {len(cells)} cells and the "
                             f"header has {len(header)}, so some of it has no column; it cannot be shown as that table")
        data.append((cells + [""] * len(header))[:len(header)])
    return header, (aligns + [None] * len(header))[:len(header)], data, lines[0]


def csv_table(root: Path, file: str, first: int, last: int, columns: list | None = None, ref: str | None = None,
              encoding: str | None = None) -> tuple[list[str], list[list[str]]]:
    """Data rows first..last (1-based, after the header) of a CSV or TSV file, with chosen columns in the chosen order."""
    import csv
    import io
    text = _read(root, file, ref, "table", encoding)
    try:
        table = [row for row in csv.reader(io.StringIO(text), delimiter="\t" if file.lower().endswith(".tsv") else ",")
                 if any(cell.strip() for cell in row)]
    except csv.Error as problem:                           # a NUL byte, one cell of a hundred thousand characters
        raise ValueError(f"{file} could not be read as a table ({problem}); if it is not a "
                         f"{'tab' if file.lower().endswith('.tsv') else 'comma'}-separated file, show its lines in a code scene") from None
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
    for k, row in enumerate(body[first - 1:last], first):
        if len(row) > len(header) and any(cell.strip() for cell in row[len(header):]):
            raise ValueError(f"{file}: data row {k} has {len(row)} cells and the header has {len(header)}, so some of "
                             "it has no column (a comma inside a cell that is not quoted?); it cannot be shown as that table")
    rows = [[(row[i] if i < len(row) else "").strip() for i in pick] for row in body[first - 1:last]]
    return [header[i] for i in pick], rows
