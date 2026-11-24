"""Graphs of functions: read a formula safely, typeset it, and sample it.

The formula is the single source for a curve: the same parsed expression is evaluated for the line on
screen and turned into the LaTeX of its label, so a label can never say one thing while the curve shows another.
Nothing here calls eval(): the text is parsed to a syntax tree and only arithmetic, `x`, a few constants
and the functions in FUNCTIONS are allowed.
"""
from __future__ import annotations

import ast
import math
import re

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
    """One parsed expression in the given variables (x for an ordinary curve)."""

    def __init__(self, text: str, variables: tuple[str, ...] = ("x",)):
        self.variables = variables
        if not isinstance(text, str) or not text.strip():
            raise ValueError("a curve needs an expression, such as \"x^2\"")
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
            if node.id not in self.variables and node.id not in CONSTANTS:
                names = " and ".join(self.variables) or "none here"
                raise ValueError(f"{self.text!r}: {node.id!r} is not known; the variable is {names}, and the "
                                 "constants are pi, e and tau")
        elif isinstance(node, ast.Constant) and type(node.value) in (int, float):
            pass
        else:
            raise ValueError(f"{self.text!r} uses something a curve cannot; write it with {_ALLOWED}")

    # ---- values --------------------------------------------------------------------------------

    def __call__(self, *values):
        """The value at the given variable values (numbers or arrays, in the order of `variables`).
        Where the formula has no real value the result is nan."""
        env = {name: np.asarray(v, dtype=float) for name, v in zip(self.variables, values)}
        shape = np.broadcast(*env.values()).shape if env else ()
        with np.errstate(all="ignore"):
            ys = np.asarray(self._value(self.node, env), dtype=float) + np.zeros(shape)
        ys = np.where(np.isfinite(ys), ys, np.nan)
        return ys if ys.ndim else float(ys)

    def _value(self, node, env):
        if isinstance(node, ast.Constant):
            return float(node.value)
        if isinstance(node, ast.Name):
            return env[node.id] if node.id in env else CONSTANTS[node.id][0]
        if isinstance(node, ast.UnaryOp):
            value = self._value(node.operand, env)
            return -value if isinstance(node.op, ast.USub) else value
        if isinstance(node, ast.Call):
            return FUNCTIONS[node.func.id][0](self._value(node.args[0], env))
        a, b = self._value(node.left, env), self._value(node.right, env)
        if isinstance(node.op, ast.Add):
            return a + b
        if isinstance(node.op, ast.Sub):
            return a - b
        if isinstance(node.op, ast.Mult):
            return a * b
        if isinstance(node.op, ast.Div):
            return np.divide(a, b)
        return np.power(a, b)

    def area(self, a: float, b: float) -> tuple[float, float]:
        """The signed area between the curve and the x axis from a to b, and how far off it may be (see `area`)."""
        return area(self, a, b)

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
            return {"theta": r"\theta"}.get(node.id, node.id) if node.id in self.variables else CONSTANTS[node.id][1]
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


def area(f, a: float, b: float) -> tuple[float, float]:
    """The signed area between f and the x axis from a to b, and how far off it may be.

    Simpson's rule at three resolutions. A number is only given when they agree: across a pole, or where
    the curve swings faster than it can be sampled, they do not, and that is an error, not an area.
    NaN when the formula has no value somewhere in the range."""
    sums, peaks, total = [], [], 0.0
    for n in (4096, 16384, 65536):
        ys = np.asarray(f(np.linspace(a, b, n + 1)), dtype=float)
        if not np.isfinite(ys).all():
            return float("nan"), 0.0
        h = (b - a) / n
        sums.append(float(h / 3 * (ys[0] + ys[-1] + 4 * ys[1:-1:2].sum() + 2 * ys[2:-1:2].sum())))
        peaks.append(float(np.abs(ys).max()))
        total = float(np.abs(ys).mean() * (b - a))                    # the area counted without sign
    # Near a pole the tallest sample keeps growing as the samples close in on it. The sums may even agree
    # with each other there (evenly spaced samples cancel across 1/x), so this is checked on its own.
    if peaks[2] > 2.5 * peaks[1] and peaks[1] > 2.5 * peaks[0]:
        raise ValueError("grows without bound")
    error = max(abs(sums[2] - sums[1]), abs(sums[1] - sums[0]) / 16)
    if error > 1e-3 * max(total, 1e-300):
        raise ValueError("cannot be measured")
    value = sums[2]
    return (0.0 if abs(value) < 1e-11 * total else value), error

# ---- LaTeX ---------------------------------------------------------------------------------


def root(f, lo: float, hi: float) -> float:
    """Where f crosses zero between lo and hi. There must be exactly one crossing in sight: with none there is
    nothing to mark, and with several the storyboard has to say which, by narrowing the range."""
    xs = np.linspace(lo, hi, 2001)
    ys = np.asarray(f(xs), dtype=float)
    if not np.isfinite(ys).all():
        raise ValueError("has no value somewhere in that range")
    live = np.nonzero(ys != 0)[0]                           # a sample that is exactly 0 sits between its neighbours' signs
    if not len(live):
        raise ValueError("is zero all the way across that range")
    above = ys[live] > 0
    turns = np.nonzero(above[:-1] != above[1:])[0]
    if len(turns) > 1:
        raise ValueError(f"crosses zero {len(turns)} times in that range; narrow it to the crossing you mean")
    if len(turns) == 0:
        zeros = np.nonzero(ys == 0)[0]
        if len(zeros) and zeros[-1] - zeros[0] == len(zeros) - 1:
            return float(xs[zeros[len(zeros) // 2]])        # it touches zero there without crossing
        raise ValueError("does not cross zero in that range")
    a, b = float(xs[live[turns[0]]]), float(xs[live[turns[0] + 1]])
    fa, start = float(f(a)), abs(float(f(a)) - float(f(b)))
    for _ in range(200):
        mid = (a + b) / 2
        fm = float(f(mid))
        if fm == 0:
            return mid
        if mid in (a, b):
            break
        if (fm > 0) == (fa > 0):
            a, fa = mid, fm
        else:
            b = mid
    if abs(float(f(a)) - float(f(b))) > 0.5 * start:        # a pole or a step also changes sign, without passing through 0
        raise ValueError("jumps across zero in that range instead of crossing it")
    return (a + b) / 2


def extremum(f, lo: float, hi: float, highest: bool) -> float:
    """Where f is largest (or smallest) between lo and hi: the best of a fine sampling, then closed in on."""
    xs = np.linspace(lo, hi, 4001)
    ys = np.asarray(f(xs), dtype=float)
    if not np.isfinite(ys).all():
        raise ValueError("has no value somewhere in that range")
    sign = 1.0 if highest else -1.0
    k = int(np.argmax(sign * ys))
    a, b = float(xs[max(k - 1, 0)]), float(xs[min(k + 1, len(xs) - 1)])
    ratio = (math.sqrt(5) - 1) / 2
    c, d = b - ratio * (b - a), a + ratio * (b - a)
    fc, fd = sign * float(f(c)), sign * float(f(d))
    for _ in range(120):                                    # golden-section search
        if fc > fd:
            b, d, fd = d, c, fc
            c = b - ratio * (b - a)
            fc = sign * float(f(c))
        else:
            a, c, fc = c, d, fd
            d = a + ratio * (b - a)
            fd = sign * float(f(d))
    x = (a + b) / 2
    for end in (lo, hi):                                    # the very end of the range, if that is where it is
        if sign * float(f(end)) >= sign * float(f(x)):
            x = end
    return x


def minus(text: str) -> str:
    """The same number with a real minus sign, for text that is not typeset as math."""
    return text.replace("-", "\u2212")


_RAISED = str.maketrans("-0123456789", "⁻⁰¹²³⁴⁵⁶⁷⁸⁹")


def _parts(value: float, digits: int) -> tuple[str, int | None]:
    """A number as (digits to show, power of ten or None): 0.000012 is ("1.2", -5), 42 is ("42", None)."""
    if value == 0 or not math.isfinite(value):
        return "0", None
    power = int(math.floor(math.log10(abs(value))))
    if -4 <= power < 9:                                    # ordinary size: written out, no exponent
        text = f"{value:.{max(0, digits - 1 - power)}f}"
        if "." in text:
            text = text.rstrip("0").rstrip(".")
        return ("0" if text in ("-0", "") else text), None
    lead = f"{value / 10 ** power:.{digits - 1}f}"
    if abs(float(lead)) >= 10:                             # 9.9996 rounded up to 10.00
        lead, power = f"{float(lead) / 10:.{digits - 1}f}", power + 1
    return lead.rstrip("0").rstrip("."), power


def number(value: float, digits: int = 4) -> str:
    """A number as plain text on screen: up to `digits` significant figures and no trailing zeros. Very large
    and very small numbers are written with a power of ten (1.2×10⁻⁵) instead of a row of zeros."""
    lead, power = _parts(value, digits)
    if power is None:
        return lead
    return (f"{lead}×" if lead not in ("1", "-1") else "-" * (lead == "-1")) + "10" + str(power).translate(_RAISED)


def number_tex(value: float, digits: int = 4) -> str:
    """The same number as LaTeX, for a label typeset as math."""
    lead, power = _parts(value, digits)
    if power is None:
        return lead
    return (rf"{lead} \times " if lead not in ("1", "-1") else "-" * (lead == "-1")) + f"10^{{{power}}}"


def shown(value: float, digits: int = 4) -> float:
    """The value that number(value) puts on screen."""
    lead, power = _parts(value, digits)
    return float(lead) * (10.0 ** power if power is not None else 1.0)


def rounded(value: float, error: float = 0.0, digits: int = 4) -> bool:
    """True when the number on screen is not the value itself, so a label should say "about": the digits had
    to be cut, or the value is only known to within `error`."""
    if value == 0:
        return False                                        # set to zero on purpose: nothing was cut off
    gap = abs(shown(value, digits) - value)
    return gap > max(4 * error, 1e-7 * abs(value)) or error > 1e-6 * max(abs(value), 1e-300)


def tidy(value: float, span: float) -> float:
    """A coordinate kept to a ten-millionth of the range it is drawn in: a fixed number of decimals would
    flatten a curve whose whole range is a billionth."""
    if not math.isfinite(value) or not math.isfinite(span) or span <= 0:
        return value
    return round(value, 7 - int(math.floor(math.log10(span))))


def settled(f, x: float) -> float:
    """f(x), or 0 when the value is nothing but rounding noise: sin(pi) comes out as 1.2e-16 and changes sign
    with the last bit of pi, while exp(-50) is a real, tiny number."""
    y = float(f(x))
    if y == 0 or not math.isfinite(y):
        return y
    near = [float(f(v)) for v in (math.nextafter(x, -math.inf), math.nextafter(x, math.inf),
                                  math.nextafter(math.nextafter(x, -math.inf), -math.inf),
                                  math.nextafter(math.nextafter(x, math.inf), math.inf))]
    if any(v != v for v in near) or max(near + [y]) - min(near + [y]) > 0.5 * abs(y):
        return 0.0
    return y


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


def fixed(value: float) -> str:
    """A number with two decimals and a real minus sign: for a label that changes while a point travels,
    so its width holds still."""
    text = f"{value:.2f}"
    return minus("0.00" if text == "-0.00" else text)


def upright(dx: float, dy: float, wide: float, high: float) -> bool:
    """A direction that is vertical on the graph."""
    return abs(dx) * high < 1e-7 * abs(dy) * wide


def slope_text(dx: float, dy: float, wide: float, high: float) -> str:
    if upright(dx, dy, wide, high):
        return "vertical"
    return f"slope {fixed(dy / dx)}"


def heading(path, s: float, reach: float, wide: float, high: float, lo: float | None = None,
            hi: float | None = None) -> tuple[float, float, float]:
    """The direction of the tangent line to a curve at parameter s: (dx, dy, uncertainty of dy/dx).

    `path(s)` gives (x, y); for a function of x it is (x, f(x)). The tangent is the line that chords from the
    point settle on as they shorten, from either side. It is looked for, not assumed: at a corner or a jump
    the two sides settle on different lines, and that raises ValueError with the reason instead of drawing
    one of them. `reach` is the size of s across the graph; `lo` and `hi` are the ends of the curve, if any."""
    x, y = (float(v) for v in path(s))
    grain = 1e3 * np.finfo(float).eps

    def chord(h: float):
        """The chord from the point to path(s + h), in graph units and in screen proportions."""
        px, py = (float(v) for v in path(s + h))
        if px != px or py != py:
            return None
        dx, dy = (px - x) * math.copysign(1, h), (py - y) * math.copysign(1, h)
        if abs(dx) <= grain * max(abs(x), abs(px)) and abs(dy) <= grain * max(abs(y), abs(py)):
            return None                                     # too short to tell from rounding
        return dx, dy

    def lean(dx: float, dy: float) -> float:
        """The angle of a line on screen, from 0 to pi."""
        return math.atan2(dy / high, dx / wide) % math.pi

    def apart(a: float, b: float) -> float:
        return min(abs(a - b), math.pi - abs(a - b))

    sides = []
    for sign, end in ((1, hi), (-1, lo)):
        if end is not None and (end - s) * sign <= 1e-12 * reach:
            continue                                        # the curve ends here: only one side to look at
        found = []
        for k in range(4, 36):
            h = sign * reach * 2.0 ** -k
            c = chord(h)
            if c is None:
                if found:
                    break
                continue
            found.append((abs(h), c))
        sides.append(found)
    if not sides or any(len(found) < 6 for found in sides):
        raise ValueError("has no tangent")

    def settle(found):
        """(angle the chords settle on, True if they are still swinging, True if they keep steepening)."""
        angles = [lean(*c) for _, c in found]
        steep = [abs(c[1] / high) / max(abs(c[0] / wide), 1e-300) for _, c in found]
        best = min(range(2, len(found)), key=lambda i: apart(angles[i], angles[i - 1]) + apart(angles[i - 1], angles[i - 2]))
        swinging = apart(angles[best], angles[best - 1]) > 1e-3
        tail = steep[max(best - 8, 0): best + 1]
        rising = len(tail) >= 6 and all(b >= 1.2 * a for a, b in zip(tail, tail[1:]))
        return angles[best], swinging, rising, found[best], found[best - 1]

    settled_ = [settle(found) for found in sides]
    if all(side[2] for side in settled_):
        return 0.0, 1.0, 0.0                                # every side steepens without end: a vertical tangent
    if any(side[1] for side in settled_):
        raise ValueError("has no tangent (the curve does not settle on one direction)")
    if len(settled_) == 2 and apart(settled_[0][0], settled_[1][0]) > 2e-3:
        if any(side[2] for side in settled_):
            raise ValueError("has no tangent (the curve jumps)")
        raise ValueError("has no tangent (the curve has a corner)")

    # The line exists. Its slope, as precisely as the formula allows: central differences, extrapolated.
    if len(settled_) == 2:
        best, previous = None, None
        for k in range(4, 40):
            h = reach * 2.0 ** -k
            a, b = path(s + h), path(s - h)
            d = ((float(a[0]) - float(b[0])) / (2 * h), (float(a[1]) - float(b[1])) / (2 * h))
            if any(v != v for v in d):
                break
            if previous is not None:
                r = ((4 * d[0] - previous[1][0]) / 3, (4 * d[1] - previous[1][1]) / 3)
                if previous[0] is not None:
                    change = math.hypot((r[0] - previous[0][0]) / wide, (r[1] - previous[0][1]) / high)
                    size = math.hypot(r[0] / wide, r[1] / high)
                    if best is None or change < best[0]:
                        best = (change, size, r, previous[0])
                previous = (r, d)
            else:
                previous = (None, d)
        if best and best[1] > 0 and best[0] <= 1e-3 * best[1]:
            dx, dy = best[2]
            if upright(dx, dy, wide, high):
                return 0.0, 1.0, 0.0
            if abs(dx) > 0:
                slope, before = dy / dx, (best[3][1] / best[3][0] if best[3][0] else dy / dx)
                if abs(lean(dx, dy) - settled_[0][0]) < 0.05 or apart(lean(dx, dy), settled_[0][0]) < 0.05:
                    return 1.0, slope, abs(slope - before)
    # At a standstill (a cusp, or a curve that pauses) the differences vanish; the chords still give the line.
    (_, (dx, dy)), (_, (wx, wy)) = settled_[0][3], settled_[0][4]       # the shortest good chord, and one twice as long
    if upright(dx, dy, wide, high) or math.cos(settled_[0][0]) ** 2 < 1e-12:
        return 0.0, 1.0, 0.0
    near, far = dy / dx, (wy / wx if wx else dy / dx)
    return 1.0, 2 * near - far, abs(near - far)             # a chord is off by about its length; take that out


def view(curves: list[Formula], x0: float, x1: float) -> tuple[float, float]:
    """A y range for functions of x over [x0, x1]."""
    xs = np.linspace(x0, x1, SAMPLES)
    return view_of([f(xs) for f in curves])


def view_of(heights: list, whole: list | None = None) -> tuple[float, float]:
    """A y range that shows what the curves do without letting an asymptote flatten everything else.

    `whole` says, per curve, that it stays bounded (see `runs_away`): such a curve is shown top to bottom,
    however thin its peak. Only a curve that shoots off to infinity is cut, to keep the rest readable."""
    ys = np.concatenate([np.asarray(h, dtype=float) for h in heights])
    ys = ys[np.isfinite(ys)]
    if not len(ys):
        raise ValueError("none of the curves has a value anywhere in the x range")
    lo, hi = float(ys.min()), float(ys.max())
    q1, q3 = (float(v) for v in np.percentile(ys, [25, 75]))
    body = max(q3 - q1, 1e-9 * max(abs(lo), abs(hi), 1e-300))
    lo, hi = max(lo, q1 - 6 * body), min(hi, q3 + 6 * body)             # cut runaway ends, keep ordinary ones whole
    for h, keep in zip(heights, whole or []):
        h = np.asarray(h, dtype=float)
        h = h[np.isfinite(h)]
        if keep and len(h):
            lo, hi = min(lo, float(h.min())), max(hi, float(h.max()))
    if not math.isfinite(hi - lo) or hi - lo > 1e280:
        raise ValueError("the curves reach values too large to draw over this x range; show a narrower range")
    if hi - lo < 1e-9 * max(abs(lo), abs(hi), 1e-300) or hi == lo:
        gap = max(abs(lo), 1.0) if hi == lo else (hi - lo)
        lo, hi = lo - gap, hi + gap
    pad = (hi - lo) * 0.07
    lo, hi = lo - pad, hi + pad
    if 0 < lo < 0.3 * hi:                                               # close to zero: show the axis
        lo = 0.0
    if 0.3 * lo < hi < 0:
        hi = 0.0
    return lo, hi


def sampled(path, s0: float, s1: float, x0: float, x1: float, y0: float, y1: float):
    """Points along a curve, dense enough that the line through them is the curve: (s, x, y, y halfway).

    Between every two samples the curve is looked at again, at three places. If the straight line between
    the samples misses them, the curve bends faster than the samples can follow, and it is sampled four
    times as finely. (Halfway alone is not enough: a fast wave can line up with the samples and with the
    points halfway between them, and look like a slow one at both.) A curve that still cannot be followed (sin(5000 x) across six units) is not drawn at
    all: joining too few samples of it would draw a slower wave that is not there."""
    wide, high = x1 - x0, y1 - y0
    missed = 0.0
    for count in (SAMPLES, SAMPLES * 4, SAMPLES * 16):
        ss = np.linspace(s0, s1, count)
        xs, ys = path(ss)
        seen = np.isfinite(xs[:-1]) & np.isfinite(xs[1:]) & np.isfinite(ys[:-1]) & np.isfinite(ys[1:])
        with np.errstate(invalid="ignore"):
            for a, lo, hi in ((xs[:-1], x0, x1), (xs[1:], x0, x1), (ys[:-1], y0, y1), (ys[1:], y0, y1)):
                seen &= (a >= lo) & (a <= hi)
        off = np.zeros(count - 1)
        my = None
        for part in (0.5, 0.381966, 0.707107):
            px, py = path(ss[:-1] + part * (ss[1:] - ss[:-1]))
            if my is None:
                my = py
            with np.errstate(invalid="ignore"):
                seen &= np.isfinite(px) & np.isfinite(py) & (px >= x0) & (px <= x1) & (py >= y0) & (py <= y1)
                gap = np.maximum(np.abs(px - (xs[:-1] + part * (xs[1:] - xs[:-1]))) / wide,
                                 np.abs(py - (ys[:-1] + part * (ys[1:] - ys[:-1]))) / high)
            off = np.fmax(off, gap)
        missed = float((off[seen] > 0.004).mean()) if seen.any() else 0.0
        if missed <= 0.02:
            break
    if missed > 0.15:
        raise ValueError("turns back and forth too fast to be drawn over this range; show a narrower range")
    return ss, xs, ys, my


def runs_away(values, s0: float, s1: float) -> bool:
    """Whether a curve shoots off without bound somewhere in a range (1/x near 0).

    The tallest sample is looked at more and more closely. Beside a pole it is ten times taller at every closer
    look; at the top of a peak, however thin, it stops growing once the top is found."""
    ss = np.linspace(s0, s1, SAMPLES * 8 + 1)
    grew = still = 0
    peak = None
    for _ in range(7):
        with np.errstate(all="ignore"):
            ys = np.abs(np.asarray(values(ss), dtype=float))
        ys = np.where(np.isfinite(ys), ys, -1.0)
        k = int(ys.argmax())
        if ys[k] < 0:
            return False
        if peak is not None:
            still = still + 1 if ys[k] <= 1.02 * peak else 0
            if still == 2:
                return False                                # two closer looks, no taller: the top has been found
            grew += ys[k] >= 5 * peak                       # (one look may gain nothing: a sample sat by the pole by luck)
            if grew == 2:
                return True
        peak = float(ys[k])
        ss = np.linspace(ss[max(k - 1, 0)], ss[min(k + 1, len(ss) - 1)], 201)
    return False


def strokes(f: Formula, x0: float, x1: float, y0: float, y1: float) -> list[list[list[float]]]:
    """The curve as polylines in data coordinates. A line stops where the formula has no value, is not drawn
    across a jump from one side of the view to the other (the two arms of 1/x are separate lines), and is
    not drawn up a step (the treads of floor(x) are separate lines)."""
    xs, _, ys, halfway = sampled(lambda v: (v, f(v)), x0, x1, x0, x1, y0, y1)
    if 0 < np.isfinite(ys).sum() < 0.01 * len(ys):
        raise ValueError("has a value only at scattered points of this range, so there is no curve to draw")
    wide, span = x1 - x0, y1 - y0
    floor, ceiling = y0 - span, y1 + span

    def dot(x: float, y: float) -> list[float]:
        return [tidy(x, wide), tidy(min(max(y, floor), ceiling), span)]

    def edge(inside: float, outside: float) -> list[float] | None:
        """Where the formula stops having a value, between a sample that has one and a neighbour that has none."""
        for _ in range(40):
            mid = (inside + outside) / 2
            if math.isnan(f(mid)):
                outside = mid
            else:
                inside = mid
        value = f(inside)
        return None if math.isnan(value) else dot(inside, value)

    def step(left: float, right: float, drop: float):
        """A jump between two samples: the points on either side of it, or None if the curve only runs steeply."""
        for _ in range(44):
            mid = (left + right) / 2
            value = f(mid)
            if math.isnan(value):
                return None
            if abs(value - f(left)) > abs(value - f(right)):
                right = mid
            else:
                left = mid
        a, b = f(left), f(right)
        return (dot(left, a), dot(right, b)) if abs(b - a) > 0.9 * abs(drop) else None

    lines: list[list[list[float]]] = []
    current: list[list[float]] = []
    previous = last_x = None
    for k, (x, y) in enumerate(zip(xs.tolist(), ys.tolist())):
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
        jumped = previous is not None and ((previous > y1 and y < y0) or (previous < y0 and y > y1)
                                           or abs(y - previous) > 2 * span)
        if previous is not None and not jumped and abs(y - previous) > 0.003 * span:
            mid = float(halfway[k - 1])
            if mid == mid and abs(mid - (y + previous) / 2) > 0.4 * abs(y - previous):     # all of the rise is on one side
                sides = step(last_x, x, y - previous)
                if sides:
                    current.append(sides[0])
                    if len(current) > 1:
                        lines.append(current)
                    current = [sides[1]]
        last_x = x
        if jumped:
            if len(current) > 1:
                lines.append(current)
            current = []
        current.append(dot(x, y))
        previous = y
    if len(current) > 1:
        lines.append(current)
    return lines


def constant(value) -> tuple[float, str | None]:
    """A number given as a number, or as an expression without variables such as "2*pi" or "pi/2".
    Returns the value and, for an expression, its LaTeX (so a label can say pi/2 instead of 1.571)."""
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ValueError(f"{value!r} is not a number; write a number, or an expression such as \"pi/2\"")
    if isinstance(value, (int, float)):
        return float(value), None
    formula = Formula(value, ())
    number_ = formula()
    if number_ != number_:
        raise ValueError(f"{value!r} has no value")
    return float(number_), formula.tex()


def pi_ticks(lo: float, hi: float, about: int = 8) -> list[tuple[float, str]]:
    """Positions at round fractions of pi between lo and hi, with labels such as −π/2, π and 3π/2."""
    span = (hi - lo) / math.pi
    steps = [1, 2, 4, 8] + [4 * m * 10 ** p for p in range(0, 300) for m in (5, 10, 20)]     # in quarters of pi
    quarter = next((q for q in steps if span * 4 / q <= about), None)                        # step is quarter × π/4
    if quarter is None:
        return []
    first = math.ceil(lo / (math.pi / 4 * quarter) - 1e-9)
    out = []
    for k in range(first, first + 400):
        n = k * quarter                                    # the tick is n × π/4
        value = n * math.pi / 4
        if value > hi + 1e-9:
            break
        g = math.gcd(abs(n), 4)
        top, bottom = abs(n) // g, 4 // g
        label = "0" if n == 0 else ("−" if n < 0 else "") + ("" if top == 1 else str(top)) + "π" \
            + ("" if bottom == 1 else f"/{bottom}")
        out.append((value, label))
    return out


class Function:
    """y = f(x)."""
    kind = "function"

    def __init__(self, expr: str, name: str | None = None):
        self.f, self.name = Formula(expr), name
        self.text = self.f.text

    def tex(self) -> str:
        return f"{self.name}(x) = {self.f.tex()}" if self.name else f"y = {self.f.tex()}"

    def heights(self, x0: float, x1: float):
        return self.f(np.linspace(x0, x1, SAMPLES * 8 + 1))

    def bounded(self, x0: float, x1: float) -> bool:
        return not runs_away(self.f, x0, x1)

    def strokes(self, x0, x1, y0, y1):
        return strokes(self.f, x0, x1, y0, y1)

    def at(self, x: float) -> tuple[float, float]:
        return x, self.f(x)

    def direction(self, x: float, wide: float, high: float) -> tuple[float, float, float]:
        """(dx, dy, uncertainty of the slope) of the tangent at x; ValueError where there is none."""
        return heading(lambda v: (v, self.f(v)), x, wide, wide, high)


class Integral:
    """F(x) = the signed area under g from a to x, as a function that can be drawn, marked and measured like
    any other. Worked out by Gauss-Legendre quadrature over 2048 cells of [lo, hi], so it is smooth enough
    for its own slope to be taken (and that slope is g: the fundamental theorem, shown instead of asserted)."""

    _NODES = np.array([-0.9061798459386640, -0.5384693101056831, 0.0, 0.5384693101056831, 0.9061798459386640])
    _WEIGHTS = np.array([0.2369268850561891, 0.4786286704993665, 0.5688888888888889, 0.4786286704993665, 0.2369268850561891])
    CELLS = 2048

    def __init__(self, g, a: float, lo: float, hi: float, text: str = "the area"):
        self.g, self.a, self.lo, self.hi, self.text = g, float(a), float(lo), float(hi), text
        if not lo <= a <= hi:
            raise ValueError("starts outside the range it is worked out over")
        self.edges = np.linspace(lo, hi, self.CELLS + 1)
        left, right = self.edges[:-1], self.edges[1:]
        cells = self._over(left, right)
        if not np.isfinite(cells).all():
            raise ValueError("has no value somewhere in the range, so there is no area to add up")
        # Where the curve has a jump or a corner, one pass over a cell is not exact: it and its two halves
        # disagree. Those few cells are split again and again around the trouble until the halves agree.
        halves = self._over(left, (left + right) / 2) + self._over((left + right) / 2, right)
        with np.errstate(all="ignore"):
            tallest = float(np.nanmax(np.abs(np.asarray(g(self.edges), dtype=float)))) or 1.0
        self.close = 1e-11 * tallest * (hi - lo) / self.CELLS
        self.rough = set(np.flatnonzero(np.abs(cells - halves) > self.close).tolist())
        self.breaks: dict[int, tuple[float, float]] = {}   # cell -> (where the curve jumps in it, the area up to there)
        for k in self.rough:
            start, end = float(left[k]), float(right[k])
            at = self._jump(start, end)
            if at is not None:
                self.breaks[k] = (at, self._fine(start, at))
                cells[k] = self.breaks[k][1] + self._fine(at, end)
            else:
                cells[k] = self._fine(start, end)
        self.sums = np.concatenate([[0.0], np.cumsum(cells)])
        self.shift = 0.0
        self.shift = float(self(a))

    def _over(self, a, b):
        mid, half = (a + b) / 2, (b - a) / 2
        with np.errstate(all="ignore"):
            return half * sum(w * np.asarray(self.g(mid + half * x), dtype=float) for x, w in zip(self._NODES, self._WEIGHTS))

    def _fine(self, a: float, b: float, depth: int = 44) -> float:
        whole, mid = float(self._over(a, b)), (a + b) / 2
        left, right = float(self._over(a, mid)), float(self._over(mid, b))
        if depth == 0 or abs(whole - left - right) <= self.close:
            return left + right
        return self._fine(a, mid, depth - 1) + self._fine(mid, b, depth - 1)

    def _jump(self, a: float, b: float) -> float | None:
        """Where between a and b the curve jumps, if it does: one step that holds most of the change across
        the cell, closed in on by halving. The area is then added up to the jump and from it, never across."""
        xs = np.linspace(a, b, 33)
        with np.errstate(all="ignore"):
            ys = np.asarray(self.g(xs), dtype=float)
        steps = np.abs(np.diff(ys))
        n = int(steps.argmax())
        if not np.isfinite(ys).all() or steps[n] <= 0.5 * (ys.max() - ys.min()) or steps[n] <= 1e-9 * max(abs(ys).max(), 1e-300):
            return None
        lo, hi, y_lo, y_hi = float(xs[n]), float(xs[n + 1]), float(ys[n]), float(ys[n + 1])
        for _ in range(60):
            mid = (lo + hi) / 2
            if mid in (lo, hi):
                break
            y = float(self.g(mid))
            if abs(y - y_lo) > abs(y_hi - y):
                hi, y_hi = mid, y
            else:
                lo, y_lo = mid, y
        return hi if abs(y_hi - y_lo) > 0.25 * steps[n] else None      # a steep stretch, not a jump: nothing to split at

    def __call__(self, x):
        xs = np.asarray(x, dtype=float)
        inside = (xs >= self.lo) & (xs <= self.hi)
        safe = np.where(inside, xs, self.lo)
        k = np.clip(np.floor((safe - self.lo) / (self.hi - self.lo) * self.CELLS).astype(int), 0, self.CELLS - 1)
        part = np.asarray(self._over(self.edges[k], safe), dtype=float)
        if self.rough:
            flat_k, flat_x, flat_part = np.atleast_1d(k).ravel(), np.atleast_1d(safe).ravel(), np.atleast_1d(part).ravel().copy()
            for n in np.flatnonzero(np.isin(flat_k, list(self.rough))):
                edge, to, split = float(self.edges[flat_k[n]]), float(flat_x[n]), self.breaks.get(int(flat_k[n]))
                flat_part[n] = split[1] + self._fine(split[0], to) if split and to > split[0] else self._fine(edge, to)
            part = flat_part.reshape(np.shape(part))
        out = np.where(inside, self.sums[k] + part - self.shift, np.nan)
        return out if out.ndim else float(out)

    def area(self, a: float, b: float) -> tuple[float, float]:
        return area(self, a, b)


class Area(Function):
    """The area function of another curve: A(x) = the integral of that curve from a to x."""

    def __init__(self, of: Function, a: float, x0: float, x1: float, name: str | None = None, a_tex: str | None = None):
        lo, hi = min(a, x0), max(a, x1)
        try:
            value, _ = area(of.f, lo, hi)
        except ValueError as problem:
            raise ValueError(f"the area under {of.text!r} cannot be added up: the curve {problem} between "
                             f"x = {number(lo)} and {number(hi)}") from None
        if value != value:
            raise ValueError(f"the area under {of.text!r} cannot be added up: the curve has no value somewhere between "
                             f"x = {number(lo)} and {number(hi)}")
        if runs_away(of.f, lo, hi):
            raise ValueError(f"the area under {of.text!r} cannot be added up: the curve shoots off without bound between "
                             f"x = {number(lo)} and {number(hi)}")
        pad = 0.05 * (hi - lo)
        try:                                               # a little past the ends, where the curve allows, so a slope can be taken at them
            self.f = Integral(of.f, a, lo - pad, hi + pad, f"the area under {of.text}")
        except ValueError:
            try:
                self.f = Integral(of.f, a, lo, hi, f"the area under {of.text}")
            except ValueError as problem:
                raise ValueError(f"the area under {of.text!r} cannot be added up: the curve {problem}") from None
        self.name, self.text, self.of, self.a_tex = name, self.f.text, of, a_tex or number_tex(a)

    def tex(self) -> str:
        if self.of.name:
            inner = f"{self.of.name}(t)"
        elif isinstance(self.of.f, Formula):
            inside = Formula(re.sub(r"(?<![A-Za-z0-9_])x(?![A-Za-z0-9_])", "t", self.of.f.text), ("t",))
            inner = inside.tex() if isinstance(inside.node, (ast.Name, ast.Constant, ast.Call)) else rf"\left({inside.tex()}\right)"
        else:
            inner = r"\ldots"
        return rf"{f'{self.name}(x)' if self.name else 'y'} = \int_{{{self.a_tex}}}^{{x}} {inner}\,dt"


class Parametric:
    """(x(t), y(t)) for t in a range."""
    kind = "parametric"

    def __init__(self, x: str, y: str, t0: float, t1: float):
        self.fx, self.fy, self.t0, self.t1 = Formula(x, ("t",)), Formula(y, ("t",)), t0, t1
        self.text = f"({self.fx.text}, {self.fy.text})"

    def tex(self) -> str:
        return rf"\left(x,\ y\right) = \left({self.fx.tex()},\ {self.fy.tex()}\right)"

    def _at(self, ts):
        return self.fx(ts), self.fy(ts)

    def heights(self, x0: float, x1: float):
        xs, ys = self._at(np.linspace(self.t0, self.t1, SAMPLES * 8 + 1))
        return ys[(xs >= x0) & (xs <= x1)]

    def bounded(self, x0: float, x1: float) -> bool:
        return not runs_away(self.fy, self.t0, self.t1)

    def strokes(self, x0, x1, y0, y1):
        _, xs, ys, _ = sampled(self._at, self.t0, self.t1, x0, x1, y0, y1)
        wide, high = x1 - x0, y1 - y0
        lines, current, previous = [], [], None
        for x, y in zip(xs.tolist(), ys.tolist()):
            if math.isnan(x) or math.isnan(y):
                if len(current) > 1:
                    lines.append(current)
                current, previous = [], None
                continue
            if previous and (abs(x - previous[0]) > 2 * wide or abs(y - previous[1]) > 2 * high):
                if len(current) > 1:
                    lines.append(current)
                current = []
            current.append([tidy(min(max(x, x0 - wide), x1 + wide), wide), tidy(min(max(y, y0 - high), y1 + high), high)])
            previous = (x, y)
        if len(current) > 1:
            lines.append(current)
        return lines

    def at(self, t: float) -> tuple[float, float]:
        return self.fx(t), self.fy(t)

    def direction(self, t: float, wide: float, high: float) -> tuple[float, float, float]:
        """(dx, dy, uncertainty of the slope) of the tangent at t; ValueError where there is none."""
        return heading(self._at, t, self.t1 - self.t0, wide, high, self.t0, self.t1)


class Polar(Parametric):
    """A curve given by its distance from the origin at each angle: r = f(theta)."""

    kind = "parametric"

    def __init__(self, r: str, t0: float, t1: float):
        self.r = Formula(r, ("theta",))
        self.t0, self.t1 = t0, t1
        self.text = f"r = {r}"
        self.fx = lambda theta: self.r(theta) * np.cos(theta)
        self.fy = lambda theta: self.r(theta) * np.sin(theta)

    def tex(self) -> str:
        return rf"r = {self.r.tex()}"


class Changing:
    """One curve that changes as the video goes: through a list of formulas (the Taylor polynomials of rising
    degree), or as a number in its formula sweeps from one value to another (sin(k x) for k from 1 to 4).

    Every stage is a real graph, sampled at the same x positions; the player moves the line from one to the next."""

    kind = "changing"

    def __init__(self, stages: list[str] | None = None, expr: str | None = None, letter: str | None = None,
                 lo: float = 0.0, hi: float = 1.0, name: str | None = None, steps: int = 48):
        if stages is not None:
            self.formulas = [Formula(text) for text in stages]
            self.values = None
            self.text = stages[0]
            self.labels = [f"y = {f.tex()}" for f in self.formulas]
            self.texts = None
            self.eval = [lambda xs, f=f: f(xs) for f in self.formulas]
        else:
            f = Formula(expr, ("x", letter))
            self.values = [lo + (hi - lo) * k / steps for k in range(steps + 1)]
            self.text = expr
            self.labels = [(f"{name}(x) = " if name else "y = ") + f.tex()]
            self.texts = [f"{letter} = {fixed(v)}" for v in self.values]
            self.eval = [lambda xs, v=v: f(xs, v) for v in self.values]

    def tex(self) -> str:
        return self.labels[0]

    def frames(self, x0: float, x1: float, y0: float, y1: float) -> tuple[list[float], list[list[float]]]:
        """The x positions, and the heights of every stage at them."""
        xs = np.linspace(x0, x1, SAMPLES)
        high = y1 - y0
        out = []
        for n, stage in enumerate(self.eval, 1):
            ys = np.asarray(stage(xs), dtype=float)
            if not np.isfinite(ys).all() or runs_away(stage, x0, x1):
                raise ValueError(f"stage {n} has no value somewhere in the x range; a curve that changes must have one "
                                 "everywhere (no poles, no gaps)")
            got = sampled(lambda v, stage=stage: (v, stage(v)), x0, x1, x0, x1, y0, y1)[0]
            if len(got) != SAMPLES:
                raise ValueError(f"stage {n} bends too fast for a curve that changes; show a narrower range")
            out.append([tidy(float(min(max(v, y0 - high), y1 + high)), high) for v in ys])
        return [tidy(float(v), x1 - x0) for v in xs], out

    def heights(self, x0: float, x1: float):
        xs = np.linspace(x0, x1, SAMPLES)
        return np.concatenate([np.asarray(stage(xs), dtype=float) for stage in self.eval])

    def bounded(self, x0: float, x1: float) -> bool:
        return True


class Implicit:
    """Every (x, y) where an equation such as x^2 + y^2 = 4 holds."""
    kind = "implicit"

    def __init__(self, equation: str):
        if not isinstance(equation, str) or equation.count("=") != 1:
            raise ValueError(f'an "equation" has one = sign, as in "x^2 + y^2 = 4"; not {equation!r}')
        left, right = equation.split("=")
        self.left, self.right = Formula(left, ("x", "y")), Formula(right, ("x", "y"))
        self.text = equation.strip()

    def tex(self) -> str:
        return f"{self.left.tex()} = {self.right.tex()}"

    def gap(self, x, y):
        return self.left(x, y) - self.right(x, y)

    def heights(self, x0: float, x1: float):
        return np.array([])

    def bounded(self, x0: float, x1: float) -> bool:
        return True

    def scale(self, x: float, y: float, wide: float, high: float) -> float:
        """How fast the two sides move apart near (x, y): what "close to equal" has to be measured against."""
        gx, gy = self.gradient(x, y, wide, high)
        return math.hypot(gx * wide, gy * high)

    def gradient(self, x: float, y: float, wide: float, high: float) -> tuple[float, float]:
        hx, hy = wide * 1e-6, high * 1e-6
        return (float((self.gap(x + hx, y) - self.gap(x - hx, y)) / (2 * hx)),
                float((self.gap(x, y + hy) - self.gap(x, y - hy)) / (2 * hy)))

    def direction(self, x: float, y: float, wide: float, high: float) -> tuple[float, float, float]:
        """(dx, dy, uncertainty of the slope) of the tangent at a point on the curve; ValueError where there is
        none: where the curve crosses itself or stops (no slope on either side of the equation), and at a
        corner (the equation changes at different rates on the two sides of the point)."""
        here = float(self.gap(x, y))

        def sided(h: float, along_x: bool) -> tuple[float, float]:
            ahead = float(self.gap(x + h, y) if along_x else self.gap(x, y + h))
            behind = float(self.gap(x - h, y) if along_x else self.gap(x, y - h))
            return (ahead - here) / h, (here - behind) / h

        rates = []
        for along_x, size in ((True, wide), (False, high)):
            (a1, b1), (a2, b2) = sided(size * 1e-5, along_x), sided(size * 1e-7, along_x)
            if any(v != v for v in (a1, b1, a2, b2)):
                raise ValueError("has no tangent")
            kink = abs(a2 - b2) * size
            rates.append((kink, abs(a1 - b1) * size, (abs(a2) + abs(b2)) * size))
        steepest = max(r[2] for r in rates)
        for kink, wider, _ in rates:
            if kink > 1e-3 * steepest and kink > 0.3 * wider:           # the two sides disagree, however close you look
                raise ValueError("has no tangent (the curve has a corner)")
        gx, gy = self.gradient(x, y, wide, high)
        if gx != gx or gy != gy or math.hypot(gx * wide, gy * high) < 1e-9 * max(steepest, 1e-300):
            raise ValueError("has no tangent")
        if upright(gy, -gx, wide, high):
            return 0.0, 1.0, 0.0
        return 1.0, -gx / gy, abs(gx / gy) * 1e-6

    def strokes(self, x0, x1, y0, y1, nx: int = 360, ny: int = 220):
        """The curve as polylines, found by marching squares: walk a grid, and wherever the two sides of the
        equation swap which is larger between neighbouring grid points, the curve passes between them."""
        xs, ys = np.linspace(x0, x1, nx + 1), np.linspace(y0, y1, ny + 1)
        grid = self.gap(xs[None, :], ys[:, None])                      # grid[j, i] at (xs[i], ys[j])
        grid = np.broadcast_to(grid, (ny + 1, nx + 1)).astype(float)
        known = grid[np.isfinite(grid)]
        finite = np.abs(known)
        if not len(finite):
            return []
        typical = float(np.median(finite))                              # a jump across a pole is far above this
        # A curve is found where the two sides swap which is larger. Two kinds of equation never show that,
        # and are refused instead of drawn wrong or left blank:
        if (known == 0).mean() > 0.02:
            raise ValueError("holds over a whole region, not along a curve, so there is no curve to draw")
        if not ((known > 0).any() and (known < 0).any()):
            if float(finite.min()) <= 1e-3 * max(typical, 1e-300):
                raise ValueError("has two sides that touch without crossing (as in a square set equal to 0), "
                                 "which cannot be traced; write the equation without the square")
            return []

        def crossings(a, b, at, fixed, along_x: bool):
            """For grid edges whose ends differ in sign: where on the edge the gap is zero (0 to 1), and whether it
            really passes through zero there. Halving the edge again and again closes in on a crossing; if the
            gap stays as far apart as it started, it jumps (a step, or a pole) and there is no curve."""
            with np.errstate(invalid="ignore"):
                flips = np.isfinite(a) & np.isfinite(b) & ((a > 0) != (b > 0))
            where = np.full(a.shape, 0.5)
            if not flips.any():
                return flips, where
            lo, hi = np.zeros(int(flips.sum())), np.ones(int(flips.sum()))
            start, step = at[0][flips], at[1][flips]
            other = fixed[flips]
            ga, gb = a[flips].copy(), b[flips].copy()
            first = np.abs(ga - gb)
            for _ in range(10):
                mid = (lo + hi) / 2
                pos = start + mid * step
                gm = self.gap(pos, other) if along_x else self.gap(other, pos)
                gm = np.where(np.isfinite(gm), gm, np.inf)
                left = (gm > 0) != (ga > 0)                              # the sign change is in the first half
                hi, gb = np.where(left, mid, hi), np.where(left, gm, gb)
                lo, ga = np.where(left, lo, mid), np.where(left, ga, gm)
            real = np.isfinite(ga) & np.isfinite(gb) & (np.abs(ga - gb) <= 0.5 * first)
            flips[flips] = real
            where[flips] = ((lo + hi) / 2)[real]
            return flips, where

        X, Y = np.meshgrid(xs, ys)
        dx, dy = xs[1] - xs[0], ys[1] - ys[0]
        # horizontal edges run from (i, j) to (i + 1, j); vertical ones from (i, j) to (i, j + 1)
        h_flip, h_at = crossings(grid[:, :-1], grid[:, 1:], (X[:, :-1], np.full((ny + 1, nx), dx)), Y[:, :-1], True)
        v_flip, v_at = crossings(grid[:-1, :], grid[1:, :], (Y[:-1, :], np.full((ny, nx + 1), dy)), X[:-1, :], False)

        ends: dict[tuple, list[float]] = {}                             # a grid edge the curve crosses -> the point
        links: dict[tuple, list[tuple]] = {}
        for j in range(ny):
            for i in range(nx):
                a, b, c, d = grid[j, i], grid[j, i + 1], grid[j + 1, i + 1], grid[j + 1, i]
                if a != a or b != b or c != c or d != d:
                    continue
                if min(abs(a), abs(b), abs(c), abs(d)) > typical:
                    continue
                found = []
                if h_flip[j, i]:
                    found.append(("h", i, j, xs[i] + h_at[j, i] * dx, ys[j]))
                if v_flip[j, i + 1]:
                    found.append(("v", i + 1, j, xs[i + 1], ys[j] + v_at[j, i + 1] * dy))
                if h_flip[j + 1, i]:
                    found.append(("h", i, j + 1, xs[i] + h_at[j + 1, i] * dx, ys[j + 1]))
                if v_flip[j, i]:
                    found.append(("v", i, j, xs[i], ys[j] + v_at[j, i] * dy))
                if len(found) == 4:                                     # a saddle: pair the crossings by the centre's sign
                    centre = (a + b + c + d) / 4
                    found = [found[0], found[1], found[2], found[3]] if (centre > 0) == (a > 0) \
                        else [found[0], found[3], found[1], found[2]]
                for k in range(0, len(found) - 1, 2):
                    p, q = found[k], found[k + 1]
                    for one, other in ((p, q), (q, p)):
                        ends[one[:3]] = [tidy(float(one[3]), x1 - x0), tidy(float(one[4]), y1 - y0)]
                        links.setdefault(one[:3], []).append(other[:3])
        lines, seen = [], set()
        # Open lines first (they start at a crossing with one neighbour), then closed loops.
        for start in sorted(links, key=lambda k: (len(links[k]) != 1, k)):
            if start in seen:
                continue
            line, here, came = [ends[start]], start, None
            seen.add(start)
            while True:
                onward = [n for n in links[here] if n != came and n not in seen]
                if not onward:
                    if len(links[here]) == 2 and start in links[here] and len(line) > 2:
                        line.append(ends[start])                        # close the loop
                    break
                came, here = here, onward[0]
                seen.add(here)
                line.append(ends[here])
            if len(line) > 1:
                lines.append(line)
        return lines
