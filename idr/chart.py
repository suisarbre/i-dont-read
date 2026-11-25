"""A chart drawn from numbers the source holds: a CSV or TSV file, a Markdown table, a LaTeX table.

The engine reads the cells; a storyboard cannot type a value in. So a chart is a way of looking at the file,
as a table scene is, and a number that is not in the file cannot appear. What would mislead is refused or
fixed by rule: bars start at zero, a column that mixes units is not drawn on one axis, and a cell that is not
a number is named instead of skipped.
"""
from __future__ import annotations

import math
import re

from . import plan, plot, source
from .plan import StoryboardError

MAX_BARS = 12        # rows of a bar chart
MAX_POINTS = 400     # rows of a line chart
_CURRENCY = "$€£¥₩"
_GAPS = "\u2009\u202f\u00a0"          # thin, narrow no-break and no-break space: how SI and LaTeX (\,) group digits
_LETTERS = "A-Za-zµμ°Ω"
# A sign, digits (grouped in threes by commas or thin spaces, never with a group that starts the number at zero),
# a decimal point, a power of ten, k or M for thousands and millions, and one unit at most.
_NUMBER = re.compile(
    r"^(?:[~≈]\s*)?(?P<cur>[" + _CURRENCY + r"])?\s*(?P<sign>[-+−])?\s*(?P<cur2>[" + _CURRENCY + r"])?\s*"
    r"(?P<whole>[1-9]\d{0,2}(?:,\d{3})+|[1-9]\d{0,2}(?:[" + _GAPS + r"]\d{3})+|\d+)?(?P<frac>\.\d+)?"
    r"(?:[eE](?P<exp>[-+]?\d{1,4}))?(?P<mag>[kKM](?![" + _LETTERS + r"]))?[ " + _GAPS + r"]*(?P<unit>\S+)?$")
# What may follow a number as its unit: a sign for a share or a ratio, a currency, or a word of letters, which may
# be a rate (req/s) or squared. No digits: "1m30s", "0x10" and "1e99999" are not a number and a unit.
_UNIT = re.compile(r"[%‰×xX" + _CURRENCY + r"]|[" + _LETTERS + r"]{1,10}(?:/[" + _LETTERS + r"]{1,8})?[²³]?")
_DECIMAL_COMMA = re.compile(r"^[-+−]?\s*(?:\d+|\d{1,3}(?:[. ]\d{3})+),\d+(?:\s*\S{1,6})?$")
_EMPTY = {"", "-", "--", "–", "—", "n/a", "N/A", "NA", "NaN", "nan", "null", "None"}
# Spellings of one unit: a column in "s" and one in "sec" measure the same thing.
_SAME = [("s", "sec", "secs", "second", "seconds"), ("ms", "msec", "msecs", "millisecond", "milliseconds"),
         ("µs", "μs", "us"), ("min", "mins", "minute", "minutes"), ("h", "hr", "hrs", "hour", "hours"),
         ("d", "day", "days"), ("KB", "kB"), ("B", "byte", "bytes"), ("%", "percent", "pct"), ("×", "x", "X"),
         ("$", "USD"), ("€", "EUR"), ("£", "GBP"), ("¥", "JPY"), ("₩", "KRW")]
_CANON = {spelling: group[0] for group in _SAME for spelling in group}
# What a header may give in brackets as the unit of its column: "time (ms)", "size [KB]", "rate (req/s)".
_KNOWN_UNITS = set("""% ‰ ns µs μs us ms s sec secs min mins h hr hrs d days B KB MB GB TB PB kB KiB MiB GiB TiB bit bits
    byte bytes bps kbps Mbps Gbps Hz kHz MHz GHz W kW MW GW Wh kWh MWh V mV A mA J kJ cal kcal K °C °F m cm mm µm μm nm km
    in ft mi g kg mg µg lb oz t L l mL ml px pt em fps rpm rps qps tps ops $ € £ ¥ ₩ USD EUR GBP JPY KRW CNY""".split())
_HEADER_UNIT = re.compile(r"[(\[]\s*([^()\[\]\s]{1,10})\s*[)\]]\s*$")
# Brackets that are as often a word or a label as a unit: (min) the minimum, (s) small, (A) plan A, (d) Cohen's d.
_AMBIGUOUS = {"min", "in", "s", "m", "d", "g", "h", "t", "l", "L", "A", "B", "K", "V", "W", "J", "em", "pt"}
_WRAPPERS = re.compile(r"\\(?:mathbf|textbf|boldsymbol|bm|mathrm|mathit|text|textit|emph|underline|num)\s*\{([^{}]*)\}")


def same(unit: str) -> str:
    """One spelling for a unit, to compare two columns by."""
    return _CANON.get(unit, unit)


def _plain(cell: str) -> str:
    """A cell as its number is written, without what a paper puts round it: $...$, \\textbf{...}, {,} and \\, between
    groups of digits, \\%. What these stand for is the same number; what is left afterwards is read strictly."""
    text = cell.strip()
    if text.count("$") >= 2 and text.count("$") % 2 == 0 and "\\$" not in text:
        text = text.replace("$", "")                    # $-0.8$, $-$0.8 and $93.1$\% are math, not money
    for _ in range(3):
        text = _WRAPPERS.sub(r"\1", text)
    text = re.sub(r"\{\s*\\(?:bf|bfseries|it|em)\b\s*([^{}]*)\}", r"\1", text)
    text = re.sub(r"^\\(?:bf|bfseries)\b\s*", "", text)
    text = text.replace("{,}", ",").replace("\\%", "%").replace("\\times", "×").replace("\\$", "$")
    text = re.sub(r"(?<=\d)\\[,;:!](?=\d{3})", "\u2009", text)
    return text.strip()


def reading(cell: str) -> tuple[float, str] | None:
    """The number a cell holds and its unit ("12.5 ms" is 12.5 and ms; "$1,200" is 1200 and $; "1.2M" is 1200000),
    or None for an empty cell. A cell that is anything else raises ValueError: a chart draws a cell only when the
    whole of it is one number, because a length drawn from the first digits of "1:45", "1,25" or "1m30s" would be
    a different number."""
    text = _plain(cell)
    if text in _EMPTY:
        return None
    m = _NUMBER.match(text)
    unit = (m["unit"] or "") if m else ""
    if not m or (m["whole"] is None and m["frac"] is None) or (m["cur"] and m["cur2"]) or (unit and not _UNIT.fullmatch(unit)):
        if _DECIMAL_COMMA.match(text):
            raise ValueError(f"{cell!r} looks like a number written with a decimal comma, and a chart reads a decimal "
                             "point (1.25), with commas only between groups of three digits (1,250)")
        raise ValueError(f"{cell!r} is not a plain number (digits, with one unit such as ms or % at most)")
    value = float(f"{re.sub('[^0-9]', '', m['whole'] or '0')}{m['frac'] or ''}e{m['exp'] or '0'}")
    value *= {"k": 1e3, "K": 1e3, "M": 1e6}.get(m["mag"], 1.0)
    if not math.isfinite(value):
        raise ValueError(f"{cell!r} is too large to draw")
    currency = m["cur"] or m["cur2"] or ""
    if currency and unit:
        raise ValueError(f"{cell!r} has two units ({currency} and {unit})")
    return (-value if m["sign"] in ("-", "−") else value), same(currency or unit)


def header_unit(name: str) -> str:
    """The unit a column's header seems to give in brackets, or "": "time (ms)" says ms. It is a hint and not a
    fact: "latency (min)" may mean the minimum, so the chart warns on it and never refuses."""
    m = _HEADER_UNIT.search(name)
    if m and (m.group(1) in _KNOWN_UNITS or ("/" in m.group(1) and _UNIT.fullmatch(m.group(1)))):
        return same(m.group(1))
    return ""


def placed(labels: list[str]) -> tuple[list[float] | None, str, str]:
    """Where the rows of a line chart go along x when their x cells are numbers: (positions, unit, "") or
    (None, "", why not). Only plain numbers in one unit, in rising order, are positions. What is written as a
    code is a name even when it is all digits: 0930 is a time and 202409 a month, and placing them as the
    numbers 930 and 202409 would draw gaps the calendar does not have."""
    try:
        got = [reading(text) for text in labels]
    except ValueError as problem:
        return None, "", str(problem)
    if any(g is None for g in got):
        return None, "", "one of them is empty"
    if len({g[1] for g in got}) > 1:
        return None, "", f"they are in different units ({', '.join(sorted({g[1] or 'none' for g in got}))})"
    if not all(a[0] < z[0] for a, z in zip(got, got[1:])):
        return None, "", "they are not in rising order"
    digits = [re.sub(r"[^\d.]", "", _plain(text)) for text in labels]
    if any(re.fullmatch(r"0\d+", d) for d in digits):
        return None, "", "they are written with leading zeros, as codes and clock times are (0930)"
    if all(re.fullmatch(r"(?:19|20)\d\d(?:0[1-9]|1[0-2])(?:[0-3]\d)?", d) for d in digits):
        return None, "", "they are written the way dates are (202409), not as measurements"
    parts = [d.partition(".")[2] for d in digits]
    if any(len(part) >= 2 and part.endswith("0") for part in parts) and len({len(part) for part in parts}) > 1:
        return None, "", "they are written the way versions are (2.10 beside 2.9), not as measurements"
    return [g[0] for g in got], got[0][1], ""


def _marks(low: float, high: float, about: int, whole: bool = False) -> list[list]:
    """Round positions between low and high, each with a label that has enough digits to tell it from the next."""
    marks = plot.ticks(low, high, about)
    if whole:                                             # positions that are all whole numbers (years) get no half-steps
        marks = [v for v in marks if abs(v - round(v)) < 1e-9] or marks
    step = min((b - a for a, b in zip(marks, marks[1:])), default=abs(high) or 1.0)
    big = max(abs(v) for v in marks) or step
    digits = max(4, int(math.floor(math.log10(big))) - int(math.floor(math.log10(step) + 1e-9)) + 1)
    return [[v, plot.minus(plot.number(v, digits))] for v in marks]


def _titled(name: str, unit: str) -> str:
    """What an axis measures: the column's name, with the unit of its cells unless the name ends in a bracket of its own."""
    if not unit or _HEADER_UNIT.search(name) or name.strip().endswith(unit):
        return name
    return f"{name} ({unit})" if name else unit


def _chart(b, spec: dict, kicker: str) -> plan.Scene:
    where = spec.get("heading") or "chart"
    if "sub" in spec:
        raise StoryboardError(f'{where}: a chart writes its own line under the heading (the file, the rows and the '
                              'columns), so it takes no "sub"; say the rest in the narration')
    plan._only(spec, {"type", "heading", "beats", "file", "lines", "rows", "ref", "encoding", "expect", "x", "y", "kind", "spacing", "skip"},
               "a chart scene", where)
    if not isinstance(spec.get("beats"), list) or not spec["beats"]:
        raise StoryboardError(f'{where}: a chart needs at least one beat: a sentence that says what the numbers show')
    for key in ("expect", "encoding", "ref"):
        if spec.get(key) is not None and not isinstance(spec[key], str):
            raise StoryboardError(f'{where}: "{key}" is a piece of text, not {spec[key]!r}')

    def span(key: str, what: str) -> tuple[int, int]:
        given = spec[key]
        if not (isinstance(given, list) and len(given) == 2 and all(isinstance(v, int) and not isinstance(v, bool) for v in given)):
            raise StoryboardError(f'{where}: "{key}" is [first, last], two whole numbers counting {what} from 1; not {given!r}')
        return given[0], given[1]

    def table(read, *args):
        try:
            return read(*args)
        except ValueError as problem:                     # the advice for a table scene (write it out) does not hold here
            text = str(problem).replace("table scene", "chart")
            for advice in (". If the table is not written that way", "; write the table out with", "; write it out with"):
                if advice in text:
                    text = text.split(advice)[0] + ('. A chart is drawn from a table in a file of the source (a .csv or .tsv '
                                                    'with "rows", a Markdown or LaTeX table with "lines"); numbers found '
                                                    "anywhere else are shown in a table or stats scene")
            raise StoryboardError(text if text.startswith(str(name)) else f"{where}: {text}") from None

    name = spec.get("file")
    if name is not None and not isinstance(name, str):
        raise StoryboardError(f'{where}: "file" is the path of a file in the source, not {name!r}')
    if not name:
        raise StoryboardError(f'{where}: a chart is drawn from a file of the source: "file" with "rows" (a .csv or .tsv) '
                              'or with "lines" (a Markdown or LaTeX table). Numbers cannot be typed into a chart; if the '
                              "source has no such file, show the numbers it does give in a table or stats scene")
    at_ref = f"  ·  as of {spec['ref']}" if spec.get("ref") else ""
    if isinstance(name, str) and name.lower().endswith((".csv", ".tsv")):
        if "rows" not in spec:
            raise StoryboardError(f'{name}: a chart from a CSV file takes "rows": [first, last] (data rows, after the header)')
        if "lines" in spec:
            raise StoryboardError(f'{name}: a CSV file is read by "rows" (data rows, after the header); it takes no "lines"')
        first, last = span("rows", "data rows")
        where = f"{name} rows {first}-{last}"
        header, rows = table(source.csv_table, b.root, name, first, last, None, spec.get("ref"), spec.get("encoding"))
        numbers = list(range(first, last + 1))            # the number each row has in the file, for messages and beats
        # `expect` pins what is read: text from the header, or from the first row shown, which catches rows that moved.
        if spec.get("expect") and spec["expect"] not in ",".join(header) and spec["expect"] not in ",".join(rows[0]):
            raise StoryboardError(f"{where}: neither the header ({','.join(header)!r}) nor row {first} ({','.join(rows[0])!r}) "
                                  f"holds the expected {spec['expect']!r}; the file has changed, so fix the rows")
        sub = f"{name}  ·  {f'row {first}' if first == last else f'rows {first}–{last}'}"
    else:
        if "lines" not in spec:
            raise StoryboardError(f'{name}: a chart from a table in a document takes "lines": [first, last] around the table')
        first, last = span("lines", "lines of the file")
        where = f"{name}:{first}-{last}"
        in_tex = isinstance(name, str) and name.lower().endswith((".tex", ".ltx"))
        header, _, rows, first_line = table(source.tex_table if in_tex else source.md_table,
                                            b.root, name, first, last, spec.get("ref"), spec.get("encoding"))
        if spec.get("expect") and spec["expect"] not in first_line:
            raise StoryboardError(f"{where}: line {first} is {first_line.strip()[:60]!r}, not the expected "
                                  f"{spec['expect']!r}; the file has changed, so fix the line range")
        sub, at_ref = plan._where(spec, first, last), ""
        numbers = list(range(1, len(rows) + 1))
        if "rows" in spec:                                # some of the table's rows, counted from 1 under its header
            lo, hi = span("rows", "the table's rows")
            if not 1 <= lo <= hi <= len(rows):
                raise StoryboardError(f'{where}: the table has {len(rows)} rows under its header; "rows" cannot be {lo} to {hi}')
            rows, numbers = rows[lo - 1:hi], numbers[lo - 1:hi]
            sub += f"  ·  {f'row {lo}' if lo == hi else f'rows {lo}–{hi}'}"
    skip = spec.get("skip", [])
    if not isinstance(skip, list) or any(isinstance(n, bool) or not isinstance(n, int) for n in skip):
        raise StoryboardError(f'{where}: "skip" is a list of row numbers to leave out, such as [3], not {skip!r}')
    for n in skip:
        if n not in numbers:
            raise StoryboardError(f'{where}: "skip" names row {n}, which is not one of the rows read ({numbers[0]} to {numbers[-1]})')
    if skip:                                              # said on screen: a chart may not drop a row in silence
        rows, numbers = ([x for x, n in zip(seq, numbers) if n not in skip] for seq in (rows, numbers))
        sub += f"{'' if 'rows' in sub or 'row ' in sub else '  ·  all rows'} except {', '.join(str(n) for n in sorted(set(skip)))}"
        if not rows:
            raise StoryboardError(f'{where}: "skip" leaves no rows to draw')
    sub += at_ref
    leave = 'leave it out with "skip": [{}]'

    def column(value, what: str) -> int:
        if isinstance(value, int) and not isinstance(value, bool):
            if not 1 <= value <= len(header):
                raise StoryboardError(f"{where}: {what} is column {value}, and the table has {len(header)}")
            return value - 1
        if isinstance(value, str) and header.count(value) > 1:
            raise StoryboardError(f"{where}: {what} is {value!r}, and {header.count(value)} columns are called that; "
                                  f"give the column's number instead (the first is 1): {', '.join(header)}")
        if isinstance(value, str) and value in header:
            return header.index(value)
        raise StoryboardError(f"{where}: {what} is {value!r}, and the columns are {', '.join(header)}")

    if "x" not in spec or "y" not in spec:
        raise StoryboardError(f'{where}: a chart needs "x" (the column of names or positions) and "y" (the column, or up '
                              f"to 3 columns, of numbers); the columns are {', '.join(header)}")
    kind = spec.get("kind", "bar")
    if kind not in ("bar", "line"):
        raise StoryboardError(f'{where}: "kind" is "bar" or "line", not {kind!r}')
    xi = column(spec["x"], '"x"')
    wanted = spec["y"] if isinstance(spec["y"], list) else [spec["y"]]
    most = 2 if kind == "bar" else 3
    if not 1 <= len(wanted) <= most:
        raise StoryboardError(f"{where}: a {kind} chart draws 1 to {most} columns of numbers, not {len(wanted)}")
    ys = [column(v, '"y"') for v in wanted]
    if xi in ys or len(set(ys)) < len(ys):
        raise StoryboardError(f'{where}: "x" and each column of "y" must be different columns; '
                              f"{header[xi]!r} is given twice" if xi in ys else
                              f'{where}: "y" names the column {header[next(y for y in ys if ys.count(y) > 1)]!r} twice')
    def numeric(cell: str) -> bool:                         # a number, but not a year: columns are often named 2023, 2024
        try:
            return reading(cell) is not None and not re.fullmatch(r"(?:19|20)\d\d", cell.strip())
        except ValueError:
            return False

    if any(numeric(header[yi]) for yi in ys):               # a column of numbers named by a number: a first row of data
        b.warn(where, f"the first line read from {name} is {', '.join(header)}, and the chart takes it for the column "
               f"names; {next(header[yi] for yi in ys if numeric(header[yi]))!r} looks like a value. If the file has no "
               "header row, its first row is missing from this chart")
    limit = MAX_BARS if kind == "bar" else MAX_POINTS
    if len(rows) > limit:
        raise StoryboardError(f"{where}: {len(rows)} rows are too many for a {kind} chart ({limit} at most); "
                              + ('give "rows": [first, last] for the ones that matter, or draw a line' if kind == "bar"
                                 else 'give "rows": [first, last] for a part of them'))
    if kind == "line" and len(rows) < 2:
        raise StoryboardError(f"{where}: a line needs at least 2 rows")

    series, units = [], []
    for yi in ys:
        values, unit = [], set()
        for n, row in zip(numbers, rows):
            try:
                got = reading(row[yi])
            except ValueError as problem:
                raise StoryboardError(f"{where}: row {n} of column {header[yi]!r}: {problem}. A chart draws numbers only: "
                                      f"{leave.format(n)}, or show the column in a table scene") from None
            if got is None and kind == "bar":
                raise StoryboardError(f"{where}: row {n} of column {header[yi]!r} is empty, and a bar needs a number: "
                                      f"{leave.format(n)}")
            values.append(got[0] if got else None)
            if got and (got[1] or got[0] != 0):         # a bare 0 is zero of whatever the column measures
                unit.add(got[1])
        if len(unit) > 1:
            raise StoryboardError(f"{where}: column {header[yi]!r} mixes units ({', '.join(sorted(u or 'none' for u in unit))}), "
                                  'and one axis cannot measure both; leave rows out with "skip", or show the column in a table scene')
        if not any(v is not None for v in values):
            raise StoryboardError(f"{where}: column {header[yi]!r} has no numbers in these rows")
        in_cells, in_header = next(iter(unit), ""), header_unit(header[yi])
        if in_cells and in_header and in_cells != in_header and in_header not in _AMBIGUOUS:
            b.warn(where, f"the header {header[yi]!r} seems to say {in_header}, and the cells under it are in {in_cells}; "
                   "if the bracket is the column's unit, the file contradicts itself and the chart shows both as written")
        series.append({"name": header[yi], "values": values, "texts": [row[yi] for row in rows]})
        units.append((in_cells, in_header))
    if len({cells for cells, _ in units}) > 1:
        raise StoryboardError(f"{where}: the columns are in different units ("
                              + ", ".join(f"{header[yi]!r} in {u}" if u else f"{header[yi]!r} with none" for yi, (u, _) in zip(ys, units))
                              + "), and one axis cannot measure both; draw them in two chart scenes")
    hinted = {hint for cells, hint in units if hint and not cells}
    if len(hinted) > 1 and not hinted <= _AMBIGUOUS:
        b.warn(where, "the headers " + " and ".join(repr(header[yi]) for yi in ys) + f" seem to give different units "
               f"({', '.join(sorted(hinted))}). If they are units, one axis cannot measure both: draw two chart scenes. "
               "If the brackets mean something else, this is fine as it is")
    shared = units[0][0] or (next(iter(hinted)) if len(hinted) == 1 and all(hint for _, hint in units) else "")
    every = [v for s in series for v in s["values"] if v is not None]
    low, high = min(every), max(every)
    if kind == "bar" or 0 <= low <= 0.6 * high or high <= 0 <= low:
        low, high = min(low, 0.0), max(high, 0.0)          # bars are lengths, so they are measured from zero
    try:
        if high == low:
            high = low + (abs(low) or 1.0)
        step = plot.ticks(low, high, 5)                   # the axis runs between round numbers that take in every value
        step = step[1] - step[0] if len(step) > 1 else high - low
        first, last_ = math.floor(low / step + 1e-9), math.ceil(high / step - 1e-9)
        bottom, top = float(f"{first * step:.12g}"), float(f"{last_ * step:.12g}")
        marks = _marks(bottom, top, max(1, last_ - first))
        if not (math.isfinite(bottom) and math.isfinite(top) and top > bottom and len(marks) >= 2
                and len({text for _, text in marks}) == len(marks)):
            raise ValueError
    except (OverflowError, ZeroDivisionError, ValueError):
        raise StoryboardError(f"{where}: the numbers in {', '.join(repr(header[yi]) for yi in ys)} run from {low:g} to "
                              f"{high:g}, which is too large, too small or too close together to mark on an axis; "
                              "show them in a table") from None
    axis = {"min": bottom, "max": top, "ticks": marks,
            "title": _titled(header[ys[0]], units[0][0]) if len(ys) == 1 else shared}

    labels = [row[xi] for row in rows]
    payload: dict = {"chart": kind, "labels": labels, "series": series, "axis": axis}
    for one in series:
        if len(series) > 1 and max(abs(v) for v in one["values"] if v is not None) < 0.02 * (top - bottom):
            b.warn(where, f"every value of {one['name']!r} is under 2% of the axis, which runs to {plot.number(top)} for "
                   "the other column, so it will lie flat along the bottom; draw it in a chart of its own")
    spacing = spec.get("spacing")
    if spacing not in (None, "even", "numbers") or (spacing and kind != "line"):
        raise StoryboardError(f'{where}: "spacing" is "even" or "numbers", on a line chart: whether the rows are spread '
                              f"evenly along x or placed by the number in {header[xi]!r}")
    if kind == "line":
        positions, x_unit, why = placed(labels)
        if spacing == "numbers" and not positions:      # asked for outright: a code read as a number is then the author's call
            try:
                got = [reading(text) for text in labels]
                if all(g is not None for g in got) and len({g[1] for g in got}) == 1 and all(a[0] < z[0] for a, z in zip(got, got[1:])):
                    positions, x_unit = [g[0] for g in got], got[0][1]
            except ValueError:
                pass
            if not positions:
                raise StoryboardError(f'{where}: "spacing": "numbers" places the rows by {header[xi]!r}, but {why}')
        if positions and spacing != "even":
            whole = all(abs(v - round(v)) < 1e-9 for v in positions)
            try:
                x_marks = _marks(positions[0], positions[-1], 6, whole)
                if len({text for _, text in x_marks}) != len(x_marks):
                    raise ValueError
            except (OverflowError, ZeroDivisionError, ValueError):
                raise StoryboardError(f"{where}: the values of {header[xi]!r} are too large or too close together to "
                                      'mark on an axis; add "spacing": "even" to spread the rows evenly') from None
            payload["x"] = {"numeric": True, "at": positions, "min": positions[0], "max": positions[-1],
                            "ticks": x_marks, "title": _titled(header[xi], x_unit)}
        else:                                           # names, dates, versions: evenly spaced, in the file's order
            count = len(labels)                         # every row is marked; the player thins labels that would collide
            keep = range(count) if count <= 24 else sorted({round(i * (count - 1) / 11) for i in range(12)})
            payload["x"] = {"numeric": False, "at": list(range(count)), "min": 0, "max": count - 1,
                            "ticks": [[i, labels[i]] for i in keep], "title": header[xi]}
    columns = ", ".join(header[i] for i in ys)
    scene = b.scene("chart", kicker, {**spec, "sub": f"{sub}  ·  {columns} by {header[xi]}"}, sub_is_source=True, **payload)
    scene.sfx.append((0.0, "whoosh"))
    ops = scene.payload["ops"]

    def spot(item, what: str) -> dict:
        if not isinstance(item, dict):
            raise StoryboardError(f'{where}: {what} takes an object such as {{"x": "{labels[0]}"}}, or a list of them; not {item!r}')
        plan._only(item, {"x", "row", "series", "as"}, f'"{what}"', where)
        if "row" in item and "x" in item:
            raise StoryboardError(f'{where}: {what} names its row by "x" (the name the file gives it) or by "row" (its number), not both')
        if "as" in item and not (isinstance(item["as"], str) and re.fullmatch(r"\w+", item["as"])):
            raise StoryboardError(f'{where}: "as" is a short name to quote the cell by, such as "small"; not {item["as"]!r}')
        if "row" in item:                                # the row's number in the file (or in the table), as "rows" counts
            if isinstance(item["row"], bool) or not isinstance(item["row"], int) or item["row"] not in numbers:
                raise StoryboardError(f"{where}: {what} names row {item['row']!r}, and the chart draws rows "
                                      + (f"{numbers[0]} to {numbers[-1]}" if numbers == list(range(numbers[0], numbers[-1] + 1))
                                         else ", ".join(str(n) for n in numbers)))
            r = numbers.index(item["row"])
        elif "x" in item:
            hits = [i for i, text in enumerate(labels) if text == str(item["x"])]
            if len(hits) != 1:
                raise StoryboardError(f"{where}: {what} looks for the row whose {header[xi]} is {str(item['x'])!r}, and "
                                      + ("none is" if not hits else f"{len(hits)} are; give \"row\" instead")
                                      + f". It holds: {', '.join(labels[:12])}{'...' if len(labels) > 12 else ''}")
            r = hits[0]
        else:
            raise StoryboardError(f'{where}: {what} needs "x" (the name of a row, as the file writes it) or "row" (its number)')
        s = 0
        names = [x["name"] for x in series]
        if "series" in item:
            if item["series"] not in names:
                raise StoryboardError(f"{where}: {what} names the column {item['series']!r}; the chart draws {', '.join(names)}")
            s = names.index(item["series"])
        elif len(series) > 1:
            raise StoryboardError(f'{where}: {what} must say which column it means, since the chart draws {len(series)}: '
                                  f'add "series": "{names[0]}" (or {", ".join(repr(n) for n in names[1:])})')
        if series[s]["values"][r] is None:
            raise StoryboardError(f"{where}: {what} points at an empty cell ({labels[r]}, {series[s]['name']})")
        return {"row": r, "series": s}

    clock = plan._Clock(b, scene, where)
    stage = plan._Stage(scene, len(series), "series", plan._staged(spec))
    lit: list[dict] = []
    for beat in spec.get("beats", []):
        made, named = [], {}
        for act in plan._actions({"beats": [beat]}):       # the cells this sentence points at, to quote them in it
            if act.get("highlight") is not None:
                for item in (act["highlight"] if isinstance(act["highlight"], list) else [act["highlight"]]):
                    at = spot(item, "highlight")
                    made.append(at)
                    if isinstance(item, dict) and item.get("as"):
                        if item["as"] in named:
                            raise StoryboardError(f'{where}: two highlights in one sentence are both named "{item["as"]}"')
                        named[item["as"]] = at

        def quoted(text):
            def fill(m):
                who, field = m.group(1), m.group(2)
                if who:
                    if who not in named:
                        raise StoryboardError(f'{where}: the narration quotes {m.group(0)}, but no highlight in that sentence is named "{who}"')
                    at = named[who]
                elif len(made) == 1:
                    at = made[0]
                else:
                    raise StoryboardError(f"{where}: the narration quotes {m.group(0)}, but that sentence highlights "
                                          f'{len(made) or "no"} cells; highlight one, or name them with "as" and write {{name.value}}')
                return series[at["series"]]["texts"][at["row"]] if field == "value" else labels[at["row"]]
            return re.sub(r"\{(?:(\w+)\.)?(value|x)\}", fill, text) if isinstance(text, str) else text

        # Braces in a chart's sentence quote a cell. Anything else in braces would be spoken and shown as written.
        for key in ("say", "speak"):
            for odd in re.findall(r"\{[^{}]*\}", beat.get(key) or "") if isinstance(beat.get(key), str) else []:
                if not re.fullmatch(r"\{(?:\w+\.)?(?:value|x)\}", odd):
                    raise StoryboardError(f'{where}: the sentence holds {odd}, which is not something a chart can quote. '
                                          "Write {value} for the highlighted cell as the file writes it, {x} for its row's "
                                          'name, or {name.value} and {name.x} for a highlight given "as": "name"')
        beat = {**beat, **{k: quoted(beat[k]) for k in ("say", "speak") if k in beat}}
        acts = clock.beat(beat)
        if beat.get("at") and lit:                        # the last sentence's highlight ends when this sentence starts
            ops.append({"op": "highlight", "t": round(clock.started + 0.05, 3), "cells": []})
            lit = []
        for t, act, src in acts:
            if "reveal" in act:
                stage.upto(act["reveal"], t)
            if "highlight" in act:
                given = act["highlight"]
                target = [] if given is None else [spot(i, "highlight") for i in (given if isinstance(given, list) else [given])]
                for cell in target:
                    if cell["series"] >= stage.visible:
                        raise StoryboardError(f"{where}: a highlight points at {series[cell['series']]['name']!r} before that "
                                              f'column is drawn; reveal it in the same beat or an earlier one ("reveal": {cell["series"] + 1})')
            else:
                target = [] if src is beat else lit
            if target != lit:
                ops.append({"op": "highlight", "t": round(t + 0.05, 3), "cells": target})
                if target:
                    scene.sfx.append((round(t + 0.05, 3), "tick"))
                lit = target
    stage.upto(len(series), clock.t)
    shown = min((op["t"] for op in ops if op["op"] == "reveal"), default=0.0)
    if shown > plan.LEAD + 1.0:
        b.warn(where, f"the chart is empty for the first {shown:.1f} seconds; reveal the first column when the first sentence starts")
    last = max((op["t"] for op in ops if op["op"] == "reveal"), default=0.0)
    clock.finish(minimum=last + (2.0 if kind == "line" else 1.9 + 0.04 * len(rows)))    # drawn, and seen, before the scene ends
    return scene
