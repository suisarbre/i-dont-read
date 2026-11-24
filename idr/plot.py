"""Graphs of functions: read a formula safely, typeset it, and sample it.

The formula is the single source for a curve: the same parsed expression is evaluated for the line on
screen and turned into the LaTeX of its label, so a label can never say one thing while the curve shows another.
Nothing here calls eval(): the text is parsed to a syntax tree and only arithmetic, `x`, a few constants
and the functions in FUNCTIONS are allowed.
"""
from __future__ import annotations

import ast
import math

import numpy as np

SAMPLES = 800
MAX_CHARS = 200

# name -> (numpy function, LaTeX with {} where the argument goes)
FUNCTIONS = {
    "sin": (np.sin, r"\sin\left({}\right)"), "cos": (np.cos, r"\cos\left({}\right)"),
    "tan": (np.tan, r"\tan\left({}\right)"),
    "asin": (np.arcsin, r"\arcsin\left({}\right)"), "acos": (np.arccos, r"\arccos\left({}\right)"),
    "atan": (np.arctan, r"\arctan\left({}\right)"),
    "sinh": (np.sinh, r"\sinh\left({}\right)"), "cosh": (np.cosh, r"\cosh\left({}\right)"),
    "tanh": (np.tanh, r"\tanh\left({}\right)"),
    "exp": (np.exp, r"e^{{{}}}"),
    "ln": (np.log, r"\ln\left({}\right)"), "log": (np.log, r"\ln\left({}\right)"),
    "log2": (np.log2, r"\log_{{2}}\left({}\right)"), "log10": (np.log10, r"\log_{{10}}\left({}\right)"),
    "sqrt": (np.sqrt, r"\sqrt{{{}}}"), "cbrt": (np.cbrt, r"\sqrt[3]{{{}}}"),
    "abs": (np.abs, r"\left|{}\right|"),
    "floor": (np.floor, r"\left\lfloor {} \right\rfloor"), "ceil": (np.ceil, r"\left\lceil {} \right\rceil"),
}
CONSTANTS = {"pi": (math.pi, r"\pi"), "e": (math.e, "e"), "tau": (math.tau, r"\tau")}
_ALLOWED = "numbers, x, + - * / ^, parentheses, pi, e, tau and " + ", ".join(sorted(FUNCTIONS))


class Formula:
    """One parsed expression in x."""

    def __init__(self, text: str):
        if not isinstance(text, str) or not text.strip():
            raise ValueError("a curve needs an expression in x, such as \"x^2\"")
        if len(text) > MAX_CHARS:
            raise ValueError(f"the expression is over {MAX_CHARS} characters")
        self.text = text.strip()
        try:
            tree = ast.parse(self.text.replace("^", "**"), mode="eval")
        except SyntaxError:
            raise ValueError(f"{self.text!r} is not an expression this can read; write it with {_ALLOWED} "
                             "(multiplication needs a *, as in 2*x)") from None
        self.node = tree.body
        self._check(self.node)

    def _check(self, node) -> None:
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow)):
            self._check(node.left)
            self._check(node.right)
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
            self._check(node.operand)
        elif isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in FUNCTIONS:
                name = node.func.id if isinstance(node.func, ast.Name) else "that"
                raise ValueError(f"{self.text!r}: there is no function {name!r}; the functions are "
                                 + ", ".join(sorted(FUNCTIONS)))
            if len(node.args) != 1 or node.keywords:
                raise ValueError(f"{self.text!r}: {node.func.id} takes one argument")
            self._check(node.args[0])
        elif isinstance(node, ast.Name):
            if node.id != "x" and node.id not in CONSTANTS:
                raise ValueError(f"{self.text!r}: {node.id!r} is not known; the variable is x, and the constants "
                                 "are pi, e and tau")
        elif isinstance(node, ast.Constant) and type(node.value) in (int, float):
            pass
        else:
            raise ValueError(f"{self.text!r} uses something a curve cannot; write it with {_ALLOWED}")

    # ---- values --------------------------------------------------------------------------------

    def __call__(self, x):
        """The value at x (a number or an array). Where the formula has no real value the result is nan."""
        xs = np.asarray(x, dtype=float)
        with np.errstate(all="ignore"):
            ys = np.asarray(self._value(self.node, xs), dtype=float) + np.zeros_like(xs)
        ys = np.where(np.isfinite(ys), ys, np.nan)
        return ys if ys.ndim else float(ys)

    def _value(self, node, xs):
        if isinstance(node, ast.Constant):
            return float(node.value)
        if isinstance(node, ast.Name):
            return xs if node.id == "x" else CONSTANTS[node.id][0]
        if isinstance(node, ast.UnaryOp):
            value = self._value(node.operand, xs)
            return -value if isinstance(node.op, ast.USub) else value
        if isinstance(node, ast.Call):
            return FUNCTIONS[node.func.id][0](self._value(node.args[0], xs))
        a, b = self._value(node.left, xs), self._value(node.right, xs)
        if isinstance(node.op, ast.Add):
            return a + b
        if isinstance(node.op, ast.Sub):
            return a - b
        if isinstance(node.op, ast.Mult):
            return a * b
        if isinstance(node.op, ast.Div):
            return np.divide(a, b)
        return np.power(a, b)

    def slope(self, x: float, span: float) -> float:
        """The derivative at x, by a central difference small against the width of the graph."""
        h = span * 1e-6
        return float((self(x + h) - self(x - h)) / (2 * h))

    def area(self, a: float, b: float) -> float:
        """The signed area between the curve and the x axis from a to b (Simpson's rule)."""
        xs = np.linspace(a, b, 2001)
        ys = self(xs)
        if np.isnan(ys).any():
            return float("nan")
        h = (b - a) / 2000
        return float(h / 3 * (ys[0] + ys[-1] + 4 * ys[1:-1:2].sum() + 2 * ys[2:-1:2].sum()))

    # ---- LaTeX ---------------------------------------------------------------------------------

    def tex(self) -> str:
        return self._tex(self.node)

    @staticmethod
    def _rank(node) -> int:
        if isinstance(node, ast.BinOp):
            return {ast.Add: 1, ast.Sub: 1, ast.Mult: 2, ast.Div: 2, ast.Pow: 4}[type(node.op)]
        if isinstance(node, ast.UnaryOp):
            return 3
        if isinstance(node, ast.Constant) and node.value < 0:
            return 3
        return 5

    def _group(self, node, wrap: bool) -> str:
        text = self._tex(node)
        return rf"\left({text}\right)" if wrap or text.startswith("-") and wrap is not None else text

    def _tex(self, node) -> str:
        if isinstance(node, ast.Constant):
            return number(float(node.value))
        if isinstance(node, ast.Name):
            return "x" if node.id == "x" else CONSTANTS[node.id][1]
        if isinstance(node, ast.UnaryOp):
            inner = self._group(node.operand, self._rank(node.operand) < 2)
            return f"-{inner}" if isinstance(node.op, ast.USub) else inner
        if isinstance(node, ast.Call):
            return FUNCTIONS[node.func.id][1].format(self._tex(node.args[0]))
        if isinstance(node.op, ast.Add):
            return f"{self._tex(node.left)} + {self._group(node.right, False)}"
        if isinstance(node.op, ast.Sub):
            return f"{self._tex(node.left)} - {self._group(node.right, self._rank(node.right) < 2)}"
        if isinstance(node.op, ast.Div):
            return rf"\frac{{{self._tex(node.left)}}}{{{self._tex(node.right)}}}"
        if isinstance(node.op, ast.Mult):
            left = self._tex(node.left)
            if self._rank(node.left) < 2:
                left = rf"\left({left}\right)"
            right = self._group(node.right, self._rank(node.right) < 2)
            # 2x and 2\sin(x) read as products; anything else gets a dot, so x·x or 2·3 cannot be misread.
            plain = (isinstance(node.left, ast.Constant) and node.left.value >= 0
                     and not right[0].isdigit() and not right.startswith("-"))
            return f"{left}{right}" if plain else rf"{left} \cdot {right}"
        base = node.left
        simple = isinstance(base, ast.Name) or (isinstance(base, ast.Constant) and base.value >= 0) \
            or (isinstance(base, ast.Call) and base.func.id != "exp")
        left = self._tex(base) if simple else rf"\left({self._tex(base)}\right)"
        return f"{left}^{{{self._tex(node.right)}}}"


def minus(text: str) -> str:
    """The same number with a real minus sign, for text that is not typeset as math."""
    return text.replace("-", "\u2212")


def number(value: float, digits: int = 4) -> str:
    """A number as it is written on screen: up to `digits` significant figures, no trailing zeros, no exponent."""
    if value == 0 or abs(value) < 1e-12:
        return "0"
    places = max(0, digits - 1 - int(math.floor(math.log10(abs(value)))))
    text = f"{value:.{places}f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text in ("-0", "") else text


def rounded(value: float) -> bool:
    """True when number(value) had to round, so a label should say "about"."""
    return abs(float(number(value)) - value) > 1e-6 * max(1.0, abs(value))


def ticks(lo: float, hi: float, about: int = 6) -> list[float]:
    """Round positions (1, 2 or 5 times a power of ten apart) between lo and hi."""
    raw = (hi - lo) / max(about, 1)
    power = 10 ** math.floor(math.log10(raw))
    step = next(m * power for m in (1, 2, 5, 10) if m * power >= raw)
    first = math.ceil(lo / step - 1e-9)
    out = []
    for k in range(first, first + 200):
        value = k * step
        if value > hi + step * 1e-9:
            break
        out.append(0.0 if abs(value) < step * 1e-9 else float(round(value, 12)))
    return out


def view(curves: list[Formula], x0: float, x1: float) -> tuple[float, float]:
    """A y range that shows what the curves do over [x0, x1] without letting an asymptote flatten everything else."""
    xs = np.linspace(x0, x1, SAMPLES)
    ys = np.concatenate([f(xs) for f in curves])
    ys = ys[np.isfinite(ys)]
    if not len(ys):
        raise ValueError("none of the curves has a value anywhere in the x range")
    lo, hi = float(ys.min()), float(ys.max())
    q1, q3 = (float(v) for v in np.percentile(ys, [25, 75]))
    body = max(q3 - q1, 1e-9)
    lo, hi = max(lo, q1 - 6 * body), min(hi, q3 + 6 * body)             # cut runaway ends, keep ordinary ones whole
    if hi - lo < 1e-9:
        lo, hi = lo - 1, hi + 1
    pad = (hi - lo) * 0.07
    lo, hi = lo - pad, hi + pad
    if 0 < lo < 0.3 * hi:                                               # close to zero: show the axis
        lo = 0.0
    if 0.3 * lo < hi < 0:
        hi = 0.0
    return lo, hi


def strokes(f: Formula, x0: float, x1: float, y0: float, y1: float) -> list[list[list[float]]]:
    """The curve as polylines in data coordinates. A line stops where the formula has no value, and is not
    drawn across a jump from one side of the view to the other (the two arms of 1/x are separate lines)."""
    xs = np.linspace(x0, x1, SAMPLES)
    ys = f(xs)
    span = y1 - y0
    floor, ceiling = y0 - span, y1 + span

    def edge(inside: float, outside: float) -> list[float] | None:
        """Where the formula stops having a value, between a sample that has one and a neighbour that has none."""
        for _ in range(40):
            mid = (inside + outside) / 2
            if math.isnan(f(mid)):
                outside = mid
            else:
                inside = mid
        value = f(inside)
        return None if math.isnan(value) else [round(inside, 6), round(min(max(value, floor), ceiling), 6)]

    lines: list[list[list[float]]] = []
    current: list[list[float]] = []
    previous = last_x = None
    for x, y in zip(xs.tolist(), ys.tolist()):
        if math.isnan(y):
            if current and last_x is not None:        # the curve ends between the last sample and this one
                end = edge(last_x, x)
                if end:
                    current.append(end)
            if len(current) > 1:
                lines.append(current)
            current, previous, last_x = [], None, x
            continue
        if not current and previous is None and last_x is not None:      # ...or starts between them
            start = edge(x, last_x)
            if start:
                current.append(start)
        last_x = x
        jumped = previous is not None and ((previous > y1 and y < y0) or (previous < y0 and y > y1)
                                           or abs(y - previous) > 2 * span)
        if jumped:
            if len(current) > 1:
                lines.append(current)
            current = []
        current.append([round(x, 6), round(min(max(y, floor), ceiling), 6)])
        previous = y
    if len(current) > 1:
        lines.append(current)
    return lines
