"""Pull real source lines out of files and syntax-highlight them.

Code shown on screen is always read from disk by path and line range. Nothing is
retyped, so a scene cannot show code that is not in the file.
"""
from __future__ import annotations

import html
from pathlib import Path

from pygments import lex
from pygments.lexers import TextLexer, get_lexer_for_filename
from pygments.token import Comment, Keyword, Name, Number, Operator, String
from pygments.util import ClassNotFound

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


def extract(root: Path, file: str, first: int, last: int) -> dict:
    """Lines first..last (1-based, inclusive) of a file, highlighted and plain."""
    path = (root / file).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"code scene points at a file that does not exist: {file}")
    text = path.read_text(encoding="utf-8", errors="replace").expandtabs(4)
    plain = text.split("\n")
    if plain and plain[-1] == "":
        plain.pop()
    if not (1 <= first <= last <= len(plain)):
        raise ValueError(f"{file} has {len(plain)} lines; cannot show lines {first}-{last}")
    chunk_plain = plain[first - 1:last]
    chunk_tokens = tokenize(path, text)[first - 1:last]

    # Drop the indentation shared by every non-blank line so nested code is not pushed right.
    indents = [len(s) - len(s.lstrip(" ")) for s in chunk_plain if s.strip()]
    cut = min(indents) if indents else 0
    return {
        "file": file,
        "first": first,
        "last": last,
        "plain": [s[cut:] for s in chunk_plain],
        "lines": [_to_html(_dedent(line, cut)) for line in chunk_tokens],
    }
