"""What the voice is given to say, when that differs from what is written.

The voice model spells out anything it does not know as a word, letter by letter: "n-th" comes out as
"en tee aitch". Captions keep the sentence as written; these respellings only reach the voice.
"""
from __future__ import annotations

import re

# "n-th" is the letter's name with "th" on the end. Each respelling was checked with `python -m idr sounds`.
_LETTER_TH = {"b": "beeth", "c": "seeth", "d": "deeth", "e": "eeth", "f": "effth", "g": "jeeth", "i": "eyeth",
              "j": "jayth", "k": "kayth", "l": "elth", "m": "emth", "n": "enth", "p": "peeth", "q": "kyewth",
              "r": "arth", "s": "essth", "t": "teeth", "u": "youth", "v": "veeth", "x": "exth", "z": "zeeth"}
_ORDINAL = {"1": "first", "2": "second", "3": "third"}
_SIGN = {"+": "plus", "-": "minus", "−": "minus"}

_HYPHENATED = re.compile(r"(?<![A-Za-z0-9])([A-Za-z])-th(?![A-Za-z])")
_JOINED = re.compile(r"(?<![A-Za-z0-9'’])([nijkmNIJKM])th(?![A-Za-z])")           # nth, ith, kth
_OFFSET = re.compile(r"(?<![A-Za-z0-9])\(?([A-Za-z])\s*([+\-−])\s*([123])\)?-?(?:st|nd|rd|th)(?![A-Za-z])")


def _letter(match: re.Match) -> str:
    return _LETTER_TH.get(match.group(1).lower(), match.group(0))


def spoken(text: str, pronounce: dict[str, str] | None = None) -> str:
    """The sentence as the voice should get it: the storyboard's own respellings first, then the built-in ones."""
    for written in sorted(pronounce or {}, key=len, reverse=True):     # longest first, so "PyPI JSON" beats "PyPI"
        said = pronounce[written]
        text = re.sub(rf"(?<![A-Za-z0-9]){re.escape(written)}(?![A-Za-z0-9])", lambda _: said, text)
    text = _OFFSET.sub(lambda m: f"{m.group(1)} {_SIGN[m.group(2)]} {_ORDINAL[m.group(3)]}", text)   # (n+1)-th
    text = _HYPHENATED.sub(_letter, text)
    return _JOINED.sub(_letter, text)


def table(value, where: str) -> dict[str, str]:
    """A checked "pronounce" table: written form -> how to say it."""
    if value is None:
        return {}
    if not isinstance(value, dict) or not all(isinstance(k, str) and k.strip() and isinstance(v, str) and v.strip()
                                              for k, v in value.items()):
        raise ValueError(f'{where}: "pronounce" maps a written word to how it is said, '
                         'for example { "PyPI": "pie pee eye" }')
    return dict(value)
