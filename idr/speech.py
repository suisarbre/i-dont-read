"""What the voice is given to say, when that differs from what is written.

The voice model reads prose well and notation badly. It spells out what it does not know ("n-th" becomes
"en tee aitch", "sinh" becomes "sin"), drops signs it has no word for ("a - b" becomes "a b", the "∈" in
"x ∈ ℝ" is silent) and reads names by English spelling rules ("Cauchy" as "caw-chee"). Captions keep the
sentence as written; what is below only reaches the voice.

Every respelling here was checked with `python -m idr sounds`, which prints the sounds the voice will make.
"""
from __future__ import annotations

import re

_GREEK = "α-ωΑ-Ω"
_ATOM = rf"(?:[A-Za-z{_GREEK}]|\d+(?:\.\d+)?)"            # one letter or one number: what a formula is made of
_NOT_IN_WORD_BEFORE, _NOT_IN_WORD_AFTER = r"(?<![\w.'’])", r"(?![\w'’])"

# ---- names and words -------------------------------------------------------------------------------------

# "n-th" is the letter's name with "th" on the end.
_LETTER_TH = {"b": "beeth", "c": "seeth", "d": "deeth", "e": "eeth", "f": "effth", "g": "jeeth", "i": "eyeth",
              "j": "jayth", "k": "kayth", "l": "elth", "m": "emth", "n": "enth", "p": "peeth", "q": "kyewth",
              "r": "arth", "s": "essth", "t": "teeth", "u": "youth", "v": "veeth", "x": "exth", "z": "zeeth"}
_ORDINAL = {"1": "first", "2": "second", "3": "third"}
_SIGN = {"+": "plus", "-": "minus", "−": "minus"}

_HYPHENATED = re.compile(r"(?<![A-Za-z0-9])([A-Za-z])-th(?![A-Za-z])")
_JOINED = re.compile(r"(?<![A-Za-z0-9'’])([nijkmNIJKM])th(?![A-Za-z])")           # nth, ith, kth
_OFFSET = re.compile(r"(?<![A-Za-z0-9])\(?([A-Za-z])\s*([+\-−])\s*([123])\)?-?(?:st|nd|rd|th)(?![A-Za-z])")
_NUMBER_TH = re.compile(r"(?<![\w.])(\d+)-(st|nd|rd|th)(?![A-Za-z])")                   # 0-th, 2-nd

# Mathematicians and terms the voice reads by English spelling. Whole words; a possessive 's is kept.
_WORDS = {
    "Cauchy": "koh-shee", "Leibniz": "libe-nits", "Lebesgue": "luh-beg", "Noether": "nurter",
    "Poincaré": "poo-ahn-kah-ray", "Poincare": "poo-ahn-kah-ray", "Poisson": "poo-ah-sohn",
    "Bernoulli": "bernoolee", "Dirichlet": "dee-ree-klay", "Lagrange": "luh-grahnj", "Laplace": "luh-plahss",
    "Lagrangian": "luh-grahn-jee-un", "Laplacian": "luh-plah-see-un", "Erdős": "air-dish", "Erdos": "air-dish",
    "L'Hôpital": "loh-pee-tahl", "L'Hopital": "loh-pee-tahl", "L’Hôpital": "loh-pee-tahl",
    "Descartes": "day-cart", "Fermat": "fair-mah", "Legendre": "luh-zhahnd", "Hermite": "air-meet",
    "Huygens": "hoy-gunz", "Stieltjes": "steel-chess", "Banach": "bah-nahk", "Fréchet": "fray-shay",
    "Frechet": "fray-shay", "Peano": "pay-ah-no", "Kronecker": "kroh-neck-er", "Bézout": "bay-zoo",
    "Bezout": "bay-zoo", "Runge": "roonguh", "Kutta": "koota", "Lipschitz": "lip-shits", "Navier": "nav-yay",
    "Dirac": "dih-rack", "Cholesky": "sho-less-kee", "Krylov": "kree-loff", "Dijkstra": "dike-struh",
    "Knuth": "kuh-nooth", "Tychonoff": "tick-uh-noff", "Wiener": "veener", "Delaunay": "duh-loh-nay",
    "Verlet": "vair-lay", "Lyapunov": "lee-ah-poo-noff",
    "abelian": "abeelian", "Abelian": "abeelian",
    "sinh": "sinch", "tanh": "tanch", "arctan": "arc tan", "arcsin": "arc sine", "arccos": "arc coss",
    "csc": "cosecant", "xi": "ξ", "QED": "Q E D", "ODE": "O D E", "ODEs": "O D E's", "iff": "if and only if",
    "w.r.t.": "with respect to", "s.t.": "such that",
    "dy": "dee why", "dt": "dee tee", "du": "dee you", "dv": "dee vee", "dz": "dee zee", "dr": "dee are", "ds": "dee ess",
}
_WORD = re.compile(r"(?<![\w.])(" + "|".join(sorted(map(re.escape, _WORDS), key=len, reverse=True)) + r")(?![\w])")
_EIGEN = re.compile(r"\b([Ee])igen(?=[a-z]|\b)")                                        # eigenvalue: a hard g
_SINE = re.compile(rf"\bsin\b(?=\s+(?:of|squared|cubed|inverse|theta|phi|alpha|beta|omega|pi|{_ATOM})\b)")

# ---- notation --------------------------------------------------------------------------------------------

# Signs the voice has no word for (it stays silent) or the wrong one ("∂" comes out as "delta").
_SYMBOLS = {
    "∈": " in ", "∉": " not in ", "⊂": " is a subset of ", "⊆": " is a subset of ",
    "∪": " union ", "∩": " intersect ", "∀": "for all ", "∃": "there exists ",
    "∇": "del ", "∂": "partial ", "∑": "the sum of ", "∏": "the product of ",
    "→": " goes to ", "⇒": " implies ", "⟹": " implies ", "⇔": " if and only if ",
    "↦": " maps to ", "ℝ": "the real numbers", "ℂ": "the complex numbers",
    "ℕ": "the natural numbers", "ℤ": "the integers", "ℚ": "the rational numbers",
    "∘": " composed with ", "⊗": " tensor ", "⊕": " direct sum ", "∅": "the empty set",
    "∛": "the cube root of ", "½": "one half", "¼": "one quarter", "¾": "three quarters",
    "″": " double prime", "′": " prime", "⋅": " times ", "∣": " divides ",
    "≡": " is identical to ", "∝": " is proportional to ", "≈": " is approximately ",
    "χ": "chi",
}
_RAISED = {"²": " squared", "³": " cubed", "ⁿ": " to the n", "⁰": " to the power 0",
           "¹": " to the power 1", "⁴": " to the fourth", "⁵": " to the fifth", "⁶": " to the sixth",
           "⁷": " to the seventh", "⁸": " to the eighth", "⁹": " to the ninth",
           "⁻¹": " inverse"}
# Signs the voice does read correctly, so they are left alone and not warned about.
_READS_FINE = set("≤≥≠±×÷°∞√∫%−…")

_FRACTIONS = {"1/2": "one half", "1/3": "one third", "2/3": "two thirds", "1/4": "one quarter", "3/4": "three quarters",
              "1/5": "one fifth", "1/8": "one eighth", "1/10": "one tenth"}
_NOT_FRACTIONS = {"n/a", "w/o", "i/o", "m/s"}
_FUNCTIONS = {"sin": "sine", "cos": "cos", "tan": "tan", "ln": "ln", "log": "log", "exp": "exp", "sqrt": "the square root",
              "sinh": "sinch", "cosh": "cosh", "tanh": "tanch", "arcsin": "arc sine", "arccos": "arc coss",
              "arctan": "arc tan", "det": "the determinant", "max": "max", "min": "min", "abs": "the absolute value"}

_CALL = re.compile(r"(?<![A-Za-z])(" + "|".join(sorted(_FUNCTIONS, key=len, reverse=True)) + rf"|[A-Za-z{_GREEK}])"
                   r"('{0,2}|[′″])\(([^()]{1,16})\)")
_PRIME = re.compile(rf"(?<![\w'‘’])([A-Za-z{_GREEK}])(''|')(?![\w'])")
_POWER = re.compile(rf"({_ATOM}|\))\^(?:\{{([^{{}}]{{1,6}})\}}|(-?{_ATOM}))")
_SUB = re.compile(rf"(?<![\w.])([A-Za-z{_GREEK}])_(?:\{{({_ATOM})\}}|({_ATOM}))(?![\w])")
_DERIVATIVE = re.compile(r"(?<![\w.])d([a-z])/d([a-z])(?![\w])")
_PARTIAL = re.compile(rf"∂([A-Za-z{_GREEK}]?)\s*/\s*∂([A-Za-z{_GREEK}])")
_OVER = re.compile(rf"(?<![\w./])({_ATOM}|d[a-z])/({_ATOM}|d[a-z])(?![\w/])")
_FACTORIAL = re.compile(r"(?<![\w.])([a-z]|\d+)!(?![\w=])")
_BARS = re.compile(r"\|([^|]{1,14})\|")
_RELATION = re.compile(rf"(?<![\w.])({_ATOM}|\))\s*(<=|>=|!=|<|>)\s*(-?{_ATOM}|\()(?![\w]|\.\d)")
_RELATED = {"<": "is less than", ">": "is greater than", "<=": "is at most", ">=": "is at least", "!=": "is not equal to"}
_MINUS = re.compile(rf"(?<![\w.])({_ATOM}|\))(?:\s+-\s+|\s*−\s*)({_ATOM}|\()(?![\w]|\.\d)")
_MINUS_TIGHT = re.compile(r"(?<![\w.-])([a-z])-(\d+)(?![\w-]|\.\d)")                        # n-1, k-2
_TIMES = re.compile(rf"(?<![\w.])({_ATOM}|\))\s*(?:\*|·)\s*({_ATOM}|\()(?![\w]|\.\d)")
_SCIENTIFIC = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)e(-?)(\d+)(?![\w]|\.\d)")
_GREEK_NEXT = re.compile(rf"(?<=[A-Za-z0-9])(?=[{_GREEK}])|(?<=[{_GREEK}])(?=[A-Za-z0-9])")
_SPACES = re.compile(r"[ \t]{2,}")
# The letter a as a quantity, not the article: before an operation or at the end of a clause.
_LETTER_A = re.compile(
    r"(?<![\w'’])([aA])(?="
    r"\s+(?:plus|minus|times|over|equals)\s+(?:[A-Za-z]\b|\d)"                                        # a plus b (not "a plus sign")
    r"|\s+(?:squared|cubed|prime|factorial|inverse)(?=\s+(?:plus|minus|times|over|equals|is|and|or)\b|\s*[,.;:)?]|\s*$)"
    r"|\s+sub\s+(?:[A-Za-z]\b|\d)"
    r"|\s+(?:is|has|goes|in|and|or)(?=\s|[,.;:)?]|$)"
    r"|\s+to\s+(?:the\b|[a-z0-9]\b)"
    r"|\s+[=+]|\s*[,.;:)?]|\s*$)")


def _power(match: re.Match) -> str:
    base, raised = match.group(1), (match.group(2) or match.group(3)).strip()
    if raised == "2":
        return f"{base} squared"
    if raised == "3":
        return f"{base} cubed"
    if raised in ("-1", "−1"):
        return f"{base} inverse" if not base[0].isdigit() else f"{base} to the minus 1"
    return f"{base} to the {'minus ' + raised[1:] if raised[0] in '-−' else raised}"


def _call(match: re.Match) -> str:
    name, marks, inside = match.group(1), match.group(2), match.group(3).strip()
    prime = {"'": " prime", "′": " prime", "''": " double prime", "″": " double prime"}.get(marks, "")
    return f"{_FUNCTIONS.get(name, name)}{prime} of {inside}"


def _over(match: re.Match) -> str:
    whole = match.group(0)
    if whole.lower() in _NOT_FRACTIONS:
        return whole
    if whole in _FRACTIONS:
        return _FRACTIONS[whole]
    top, bottom = match.group(1), match.group(2)
    if top[0].isdigit() and bottom[0].isdigit():
        return whole                                       # 11/24 may be a date, 24/7 a phrase: not ours to read
    return f"{top} over {bottom}"


def _notation(text: str) -> str:
    """Formula fragments said the way a person reads them aloud."""
    text = _SCIENTIFIC.sub(lambda m: (f"{m.group(1)} times " if m.group(1) != "1" else "")
                           + f"10 to the {'minus ' if m.group(2) else ''}{m.group(3)}", text)
    text = _CALL.sub(_call, text)
    text = _PRIME.sub(lambda m: f"{m.group(1)} {'double prime' if m.group(2) == chr(39) * 2 else 'prime'}", text)
    for sign, said in sorted(_RAISED.items(), key=lambda item: -len(item[0])):
        text = text.replace(sign, said)
    text = _POWER.sub(_power, text)
    text = _SUB.sub(lambda m: f"{m.group(1)} sub {m.group(2) or m.group(3)}", text)
    text = _DERIVATIVE.sub(lambda m: f"d{m.group(1)} by d{m.group(2)}", text)
    text = _PARTIAL.sub(lambda m: f"partial {m.group(1)} by partial {m.group(2)}".replace("  ", " "), text)
    text = _OVER.sub(_over, text)
    text = _FACTORIAL.sub(lambda m: f"{m.group(1)} factorial", text)
    text = _BARS.sub(lambda m: f"the absolute value of {m.group(1).strip()}", text)
    for _ in range(2):                                     # a < b < c: the middle term belongs to both
        text = _RELATION.sub(lambda m: f"{m.group(1)} {_RELATED[m.group(2)]} {m.group(3)}", text)
        text = _MINUS.sub(lambda m: f"{m.group(1)} minus {m.group(2)}", text)
        text = _TIMES.sub(lambda m: f"{m.group(1)} times {m.group(2)}", text)
    text = _MINUS_TIGHT.sub(lambda m: f"{m.group(1)} minus {m.group(2)}", text)
    for sign, said in _SYMBOLS.items():
        text = text.replace(sign, said)
    text = _GREEK_NEXT.sub(" ", text)                      # 2πr is "two pi r", not "two pier"
    return _SPACES.sub(" ", text).strip()


def _letter(match: re.Match) -> str:
    return _LETTER_TH.get(match.group(1).lower(), match.group(0))


def spoken(text: str, pronounce: dict[str, str] | None = None) -> str:
    """The sentence as the voice should get it: the storyboard's own respellings first, then notation read
    aloud, then the built-in respellings of names and terms."""
    for written in sorted(pronounce or {}, key=len, reverse=True):     # longest first, so "PyPI JSON" beats "PyPI"
        said = pronounce[written]
        text = re.sub(rf"(?<![A-Za-z0-9]){re.escape(written)}(?![A-Za-z0-9])", lambda _: said, text)
    text = _OFFSET.sub(lambda m: f"{m.group(1)} {_SIGN[m.group(2)]} {_ORDINAL[m.group(3)]}", text)   # (n+1)-th
    text = _HYPHENATED.sub(_letter, text)
    text = _JOINED.sub(_letter, text)
    text = _NUMBER_TH.sub(lambda m: m.group(1) + m.group(2), text)                                 # 0-th -> 0th
    text = _notation(text)
    text = _WORD.sub(lambda m: _WORDS[m.group(1)], text)
    text = _EIGEN.sub(lambda m: ("E" if m.group(1) == "E" else "e") + "ye-gun-", text)
    text = _SINE.sub("sine", text)
    return _LETTER_A.sub("eigh", text)


# What is still not sayable once all of the above has been applied: the check warns about it.
_CODE_LIKE = re.compile(r"[_\\<>{}\[\]$^|]|(?<! )=|=(?! )|\w/\w|\w\(\)|\.(py|js|ts|json|md|cpp|hpp|h|rs|go|java|html|css|sh)\b")
_MATH_SIGN = re.compile("[‖←-⏿℀-⅏⁰-₟⟀-⟿⦀-⫿]")


def trouble(text: str, pronounce: dict[str, str] | None = None) -> str | None:
    """Why a sentence will not be read as written, or None: a sign with no spoken form, or a piece of code."""
    said = spoken(text, pronounce)
    signs = sorted({c for c in _MATH_SIGN.findall(said) if c not in _READS_FINE})
    if signs:
        return f"the voice cannot read {' '.join(signs)}"
    found = _CODE_LIKE.search(said)
    if found:
        return f"code-like text ({said[max(0, found.start() - 12):found.end() + 12].strip()!r}) will not be read as written"
    return None


def table(value, where: str) -> dict[str, str]:
    """A checked "pronounce" table: written form -> how to say it."""
    if value is None:
        return {}
    if not isinstance(value, dict) or not all(isinstance(k, str) and k.strip() and isinstance(v, str) and v.strip()
                                              for k, v in value.items()):
        raise ValueError(f'{where}: "pronounce" maps a written word to how it is said, '
                         'for example { "PyPI": "pie pee eye" }')
    return dict(value)
