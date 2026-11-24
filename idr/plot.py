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
            return node.id if node.id in self.variables else CONSTANTS[node.id][1]
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


def fixed(value: float) -> str:
    """A number with two decimals and a real minus sign: for a label that changes while a point travels,
    so its width holds still."""
    text = f"{value:.2f}"
    return minus("0.00" if text == "-0.00" else text)


def slope_text(dx: float, dy: float, wide: float, high: float) -> str:
    if abs(dx) * high < 1e-7 * abs(dy) * wide:
        return "vertical"
    return f"slope {fixed(dy / dx)}"


def view(curves: list[Formula], x0: float, x1: float) -> tuple[float, float]:
    """A y range for functions of x over [x0, x1]."""
    xs = np.linspace(x0, x1, SAMPLES)
    return view_of([f(xs) for f in curves])


def view_of(heights: list) -> tuple[float, float]:
    """A y range that shows what the curves do without letting an asymptote flatten everything else."""
    ys = np.concatenate([np.asarray(h, dtype=float) for h in heights])
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
    quarter = next((q for q in (1, 2, 4, 8, 16, 32) if span * 4 / q <= about), 64)     # step is quarter × π/4
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
        return self.f(np.linspace(x0, x1, SAMPLES))

    def strokes(self, x0, x1, y0, y1):
        return strokes(self.f, x0, x1, y0, y1)

    def at(self, x: float) -> tuple[float, float]:
        return x, self.f(x)

    def direction(self, x: float, span: float) -> tuple[float, float]:
        return 1.0, self.f.slope(x, span)


class Parametric:
    """(x(t), y(t)) for t in a range."""
    kind = "parametric"

    def __init__(self, x: str, y: str, t0: float, t1: float):
        self.fx, self.fy, self.t0, self.t1 = Formula(x, ("t",)), Formula(y, ("t",)), t0, t1
        self.text = f"({self.fx.text}, {self.fy.text})"

    def tex(self) -> str:
        return rf"\left(x,\ y\right) = \left({self.fx.tex()},\ {self.fy.tex()}\right)"

    def _path(self):
        ts = np.linspace(self.t0, self.t1, SAMPLES)
        return self.fx(ts), self.fy(ts)

    def heights(self, x0: float, x1: float):
        xs, ys = self._path()
        return ys[(xs >= x0) & (xs <= x1)]

    def strokes(self, x0, x1, y0, y1):
        xs, ys = self._path()
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
            current.append([round(min(max(x, x0 - wide), x1 + wide), 6), round(min(max(y, y0 - high), y1 + high), 6)])
            previous = (x, y)
        if len(current) > 1:
            lines.append(current)
        return lines

    def at(self, t: float) -> tuple[float, float]:
        return self.fx(t), self.fy(t)

    def direction(self, t: float, span: float) -> tuple[float, float]:
        h = (self.t1 - self.t0) * 1e-6
        return float((self.fx(t + h) - self.fx(t - h)) / (2 * h)), float((self.fy(t + h) - self.fy(t - h)) / (2 * h))


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

    def scale(self, x: float, y: float, wide: float, high: float) -> float:
        """How fast the two sides move apart near (x, y): what "close to equal" has to be measured against."""
        gx, gy = self.gradient(x, y, wide, high)
        return math.hypot(gx * wide, gy * high)

    def gradient(self, x: float, y: float, wide: float, high: float) -> tuple[float, float]:
        hx, hy = wide * 1e-6, high * 1e-6
        return (float((self.gap(x + hx, y) - self.gap(x - hx, y)) / (2 * hx)),
                float((self.gap(x, y + hy) - self.gap(x, y - hy)) / (2 * hy)))

    def strokes(self, x0, x1, y0, y1, nx: int = 360, ny: int = 220):
        """The curve as polylines, found by marching squares: walk a grid, and wherever the two sides of the
        equation swap which is larger between neighbouring grid points, the curve passes between them."""
        xs, ys = np.linspace(x0, x1, nx + 1), np.linspace(y0, y1, ny + 1)
        grid = self.gap(xs[None, :], ys[:, None])                      # grid[j, i] at (xs[i], ys[j])
        finite = np.abs(grid[np.isfinite(grid)])
        if not len(finite):
            return []
        typical = float(np.median(finite))                              # a jump across a pole is far above this

        def cross(a: float, b: float) -> float:
            return a / (a - b)                                          # where between two grid points the gap is zero

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
                if (a > 0) != (b > 0):
                    found.append(("h", i, j, xs[i] + cross(a, b) * (xs[i + 1] - xs[i]), ys[j]))
                if (b > 0) != (c > 0):
                    found.append(("v", i + 1, j, xs[i + 1], ys[j] + cross(b, c) * (ys[j + 1] - ys[j])))
                if (d > 0) != (c > 0):
                    found.append(("h", i, j + 1, xs[i] + cross(d, c) * (xs[i + 1] - xs[i]), ys[j + 1]))
                if (a > 0) != (d > 0):
                    found.append(("v", i, j, xs[i], ys[j] + cross(a, d) * (ys[j + 1] - ys[j])))
                if len(found) == 4:                                     # a saddle: pair the crossings by the centre's sign
                    centre = (a + b + c + d) / 4
                    found = [found[0], found[1], found[2], found[3]] if (centre > 0) == (a > 0) \
                        else [found[0], found[3], found[1], found[2]]
                for k in range(0, len(found) - 1, 2):
                    p, q = found[k], found[k + 1]
                    for one, other in ((p, q), (q, p)):
                        ends[one[:3]] = [round(float(one[3]), 6), round(float(one[4]), 6)]
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
