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
_UNIT = r"[A-Za-zµμ°Ω%‰$€£¥₩][A-Za-z0-9µμ°Ω%‰/·²³]{0,9}"
# A sign, digits (commas only between groups of three), a decimal point, a power of ten, and one unit at most.
_NUMBER = re.compile(r"^(?:[~≈]\s*)?(?P<cur>[$€£¥₩])?\s*(?P<sign>[-+−])?\s*(?P<cur2>[$€£¥₩])?\s*"
                     r"(?P<whole>\d{1,3}(?:,\d{3})+|\d+)?(?P<frac>\.\d+)?(?:[eE](?P<exp>[-+]?\d{1,4}))?"
                     r"\s*(?P<unit>" + _UNIT + r")?$")
_DECIMAL_COMMA = re.compile(r"^[-+−]?\s*(?:\d+|\d{1,3}(?:[. ]\d{3})+),\d+(?:\s*" + _UNIT + r")?$")
# What a header may give in brackets as the unit of its column: "time (ms)", "size [KB]", "rate (req/s)".
_KNOWN_UNITS = set("""% ‰ ns µs μs us ms s sec secs min mins h hr hrs d days B KB MB GB TB PB kB KiB MiB GiB TiB bit bits
    byte bytes bps kbps Mbps Gbps Hz kHz MHz GHz W kW MW GW Wh kWh MWh V mV A mA J kJ cal kcal K °C °F m cm mm µm μm nm km
    in ft mi g kg mg µg lb oz t L l mL ml px pt em fps rpm rps qps tps ops $ € £ ¥ ₩ USD EUR GBP JPY KRW CNY""".split())
_HEADER_UNIT = re.compile(r"[(\[]\s*([^()\[\]\s]{1,10})\s*[)\]]\s*$")


def reading(cell: str) -> tuple[float, str] | None:
    """The number a cell holds and its unit ("12.5 ms" is 12.5 and ms; "$1,200" is 1200 and $), or None for an
    empty cell. A cell that is anything else raises ValueError: a chart draws a cell only when the whole of it
    is one number, because a length drawn from the first digits of "1:45" or "1,25" would be a different number."""
    text = cell.strip()
    if len(text) > 2 and text.startswith("$") and text.endswith("$") and "$" not in text[1:-1]:
        text = text[1:-1].strip()                      # $-0.8$ is how a paper writes a number in a table
    if not text or text in ("-", "–", "—", "n/a", "N/A", "NA"):
        return None
    m = _NUMBER.match(text)
    if not m or (m["whole"] is None and m["frac"] is None) or (m["cur"] and m["cur2"]):
        if _DECIMAL_COMMA.match(text):
            raise ValueError(f"{cell!r} looks like a number written with a decimal comma, and a chart reads a decimal "
                             "point (1.25), with commas only between groups of three digits (1,250)")
        raise ValueError(f"{cell!r} is not a plain number (digits, with one unit such as ms or % at most)")
    value = float(f"{(m['whole'] or '0').replace(',', '')}{m['frac'] or ''}e{m['exp'] or '0'}")
    if not math.isfinite(value) or re.fullmatch(r"[eE]\d+", m["unit"] or ""):      # 1e400, 1e99999
        raise ValueError(f"{cell!r} is too large to draw")
    currency, unit = m["cur"] or m["cur2"] or "", m["unit"] or ""
    if currency and unit:
        raise ValueError(f"{cell!r} has two units ({currency} and {unit})")
    return (-value if m["sign"] in ("-", "−") else value), currency or unit


def header_unit(name: str) -> str:
    """The unit a column's header gives in brackets, or "": "time (ms)" is in ms; "score (higher is better)" is not a unit."""
    m = _HEADER_UNIT.search(name)
    if m and (m.group(1) in _KNOWN_UNITS or ("/" in m.group(1) and re.fullmatch(_UNIT, m.group(1)))):
        return m.group(1)
    return ""


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
    """What an axis measures: the column's name, with its unit if the name does not already say it."""
    if not unit or unit in name:
        return name
    return f"{name} ({unit})" if name else unit


def _chart(b, spec: dict, kicker: str) -> plan.Scene:
    where = spec.get("heading") or "chart"
    if "sub" in spec:
        raise StoryboardError(f'{where}: a chart writes its own line under the heading (the file, the rows and the '
                              'columns), so it takes no "sub"; say the rest in the narration')
    plan._only(spec, {"type", "heading", "beats", "file", "lines", "rows", "ref", "encoding", "expect", "x", "y", "kind", "spacing"},
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
            text = str(problem)
            for advice in (". If the table is not written that way", "; write the table out with"):
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
        # `expect` pins what is read: text from the header, or from the first row shown, which catches rows that moved.
        if spec.get("expect") and spec["expect"] not in ",".join(header) and spec["expect"] not in ",".join(rows[0]):
            raise StoryboardError(f"{where}: neither the header ({','.join(header)!r}) nor row {first} ({','.join(rows[0])!r}) "
                                  f"holds the expected {spec['expect']!r}; the file has changed, so fix the rows")
        sub = f"{name}  ·  {f'row {first}' if first == last else f'rows {first}–{last}'}{at_ref}"
    else:
        if "lines" not in spec:
            raise StoryboardError(f'{name}: a chart from a table in a document takes "lines": [first, last] around the table')
        if "rows" in spec:
            raise StoryboardError(f'{name}: a table in a document is read by "lines" (the lines it is on); it takes no "rows"')
        first, last = span("lines", "lines of the file")
        where = f"{name}:{first}-{last}"
        in_tex = isinstance(name, str) and name.lower().endswith((".tex", ".ltx"))
        header, _, rows, first_line = table(source.tex_table if in_tex else source.md_table,
                                            b.root, name, first, last, spec.get("ref"), spec.get("encoding"))
        if spec.get("expect") and spec["expect"] not in first_line:
            raise StoryboardError(f"{where}: line {first} is {first_line.strip()[:60]!r}, not the expected "
                                  f"{spec['expect']!r}; the file has changed, so fix the line range")
        sub = plan._where(spec, first, last)

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
    try:                                                # column names that are all numbers are a first row of data
        if all(reading(cell) is not None for cell in header):
            b.warn(where, f"the first row of {name} ({', '.join(header)}) looks like data, not column names; if the file "
                   "has no header row, this chart has lost its first row and names its columns by numbers")
    except ValueError:
        pass
    limit = MAX_BARS if kind == "bar" else MAX_POINTS
    if len(rows) > limit:
        raise StoryboardError(f"{where}: {len(rows)} rows are too many for a {kind} chart ({limit} at most); "
                              + ('narrow "rows" to the ones that matter, or draw a line' if kind == "bar" else 'narrow the range'))
    if kind == "line" and len(rows) < 2:
        raise StoryboardError(f"{where}: a line needs at least 2 rows")

    series, units = [], []
    for yi in ys:
        values, unit = [], set()
        for n, row in enumerate(rows, 1):
            try:
                got = reading(row[yi])
            except ValueError as problem:
                raise StoryboardError(f"{where}: row {n} of column {header[yi]!r}: {problem}; a chart draws numbers only, "
                                      "so leave that row out or show the column in a table") from None
            if got is None and kind == "bar":
                raise StoryboardError(f"{where}: row {n} of column {header[yi]!r} is empty; a bar needs a number")
            values.append(got[0] if got else None)
            if got:
                unit.add(got[1])
        if len(unit) > 1:
            raise StoryboardError(f"{where}: column {header[yi]!r} mixes units ({', '.join(sorted(repr(u) for u in unit))}); "
                                  "one axis cannot measure both")
        if not any(v is not None for v in values):
            raise StoryboardError(f"{where}: column {header[yi]!r} has no numbers in these rows")
        in_cells, in_header = next(iter(unit), ""), header_unit(header[yi])
        if in_cells and in_header and in_cells != in_header:
            raise StoryboardError(f"{where}: the header {header[yi]!r} says {in_header}, and the cells under it are in "
                                  f"{in_cells}; the chart cannot tell which is meant, so show the column in a table")
        series.append({"name": header[yi], "values": values, "texts": [row[yi] for row in rows]})
        units.append(in_cells or in_header)
    if len(set(units)) > 1:
        raise StoryboardError(f"{where}: the columns are in different units ("
                              + ", ".join(f"{header[yi]!r} in {u}" if u else f"{header[yi]!r} with none" for yi, u in zip(ys, units))
                              + "), and one axis cannot measure both; draw them in two chart scenes")
    numbers = [v for s in series for v in s["values"] if v is not None]
    low, high = min(numbers), max(numbers)
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
            "title": _titled(header[ys[0]] if len(ys) == 1 else "", units[0])}

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
        # The rows are placed by their x values only when every one is a plain number in one unit, in rising
        # order. A date, a time, a version or "2 MB" after "1 KB" is a name: placing it by its first digits would
        # draw distances the file does not hold.
        positions, why = None, ""
        try:
            got = [reading(text) for text in labels]
            if any(g is None for g in got):
                why = "one of them is empty"
            elif len({g[1] for g in got}) > 1:
                why = f"they are in different units ({', '.join(sorted({g[1] or 'none' for g in got}))})"
            elif not all(a[0] < z[0] for a, z in zip(got, got[1:])):
                why = "they are not in rising order"
            elif len(places := {len(t.partition(".")[2]) for t in (re.sub(r"[^\d.]", "", text) for text in labels)}) > 1 \
                    and any(re.search(r"\.\d*0$", re.sub(r"[^\d.]", "", text)) for text in labels):
                why = "they are written the way versions are (2.10 beside 2.9), not as measurements"
            else:
                positions = [g[0] for g in got]
        except ValueError as problem:
            why = str(problem)
        if spacing == "numbers" and not positions:
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
                            "ticks": x_marks, "title": header[xi]}
        else:                                           # names, dates, versions: evenly spaced, in the file's order
            show = max(1, -(-len(labels) // 8))
            payload["x"] = {"numeric": False, "at": list(range(len(labels))), "min": 0, "max": len(labels) - 1,
                            "ticks": [[i, labels[i]] for i in range(0, len(labels), show)], "title": header[xi]}
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
        if "row" in item:
            if isinstance(item["row"], bool) or not isinstance(item["row"], int) or not 1 <= item["row"] <= len(rows):
                raise StoryboardError(f"{where}: {what} names row {item['row']!r}, and the chart has rows 1 to {len(rows)}")
            r = item["row"] - 1
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
    drawn = [v for one in series for v in one["values"] if v is not None]      # every number on the chart, for the check below
    for text in labels:
        try:
            got = reading(text)
            drawn += [got[0]] if got else []
        except ValueError:
            drawn += [float(d) for d in re.findall(r"\d+(?:\.\d+)?", text)]
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

        # A number typed into the sentence is not checked against anything. One that the chart does not draw is
        # worth a second look: it may be a cell retyped wrongly, or a claim the file does not make.
        if isinstance(beat.get("say"), str):
            for token in re.findall(r"(?<![\w{.])\d[\d,]*(?:\.\d+)?(?![\w}])", re.sub(r"\{[\w.]+\}", " ", beat["say"])):
                try:
                    typed = float(token.replace(",", ""))
                except ValueError:
                    continue
                if not any(abs(typed - v) <= 1e-9 * max(1.0, abs(v)) for v in drawn):
                    b.warn(where, f"the sentence {beat['say'][:40]!r}... says {token}, which is not a number this chart "
                           "draws; quote a cell with {value} or {x} where you can, and check any other number against the source")
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
    clock.finish(minimum=last + (1.4 if kind == "line" else 1.2 + 0.04 * len(rows)))    # drawn before the scene ends
    return scene
