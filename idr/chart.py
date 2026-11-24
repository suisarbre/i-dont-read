"""A chart drawn from numbers the source holds: a CSV or TSV file, a Markdown table, a LaTeX table.

The engine reads the cells; a storyboard cannot type a value in. So a chart is a way of looking at the file,
as a table scene is, and a number that is not in the file cannot appear. What would mislead is refused or
fixed by rule: bars start at zero, a column that mixes units is not drawn on one axis, and a cell that is not
a number is named instead of skipped.
"""
from __future__ import annotations

import re

from . import plan, plot, source
from .plan import StoryboardError

MAX_BARS = 12        # rows of a bar chart
MAX_POINTS = 400     # rows of a line chart
_NUMBER = re.compile(r"^\s*(?:[~≈]\s*)?([$€£¥₩]?)\s*([-+−]?)\s*(\d[\d,]*(?:\.\d+)?|\.\d+)(?:[eE]([-+]?\d+))?\s*([^\d\s].*)?$")


def reading(cell: str) -> tuple[float, str] | None:
    """The number a cell holds and its unit ("12.5 ms" is 12.5 and ms; "$1,200" is 1200 and $), or None for an
    empty cell. A cell that is not a number raises ValueError."""
    text = cell.strip().strip("$").strip() if cell.strip().startswith("$") and cell.strip().endswith("$") and len(cell.strip()) > 1 else cell.strip()
    if not text or text in ("-", "–", "—", "n/a", "N/A", "NA"):
        return None
    m = _NUMBER.match(text)
    if not m:
        raise ValueError(f"{cell!r} is not a number")
    currency, sign, digits, power, unit = m.groups()
    value = float(digits.replace(",", "")) * (10 ** int(power) if power else 1)
    return (-value if sign in ("-", "−") else value), (currency or (unit or "").strip())


def _titled(name: str, unit: str) -> str:
    """What an axis measures: the column's name, with its unit if the name does not already say it."""
    if not unit or unit in name:
        return name
    return f"{name} ({unit})" if name else unit


def _chart(b, spec: dict, kicker: str) -> plan.Scene:
    where = spec.get("heading") or "chart"
    plan._only(spec, {"type", "heading", "sub", "beats", "file", "lines", "rows", "ref", "encoding", "expect", "x", "y", "kind"},
               "a chart scene", where)
    name = spec.get("file")
    if not name:
        raise StoryboardError(f'{where}: a chart is drawn from a file of the source: "file" with "rows" (a .csv or .tsv) '
                              'or with "lines" (a Markdown or LaTeX table). Numbers cannot be typed into a chart; if the '
                              "source has no such file, show the numbers it does give in a table or stats scene")
    at_ref = f"  ·  as of {spec['ref']}" if spec.get("ref") else ""
    if name.lower().endswith((".csv", ".tsv")):
        if "rows" not in spec:
            raise StoryboardError(f'{name}: a chart from a CSV file takes "rows": [first, last] (data rows, after the header)')
        first, last = spec["rows"]
        where = f"{name} rows {first}-{last}"
        header, rows = source.csv_table(b.root, name, first, last, None, spec.get("ref"), spec.get("encoding"))
        if spec.get("expect") and spec["expect"] not in ",".join(header):
            raise StoryboardError(f"{where}: the header is {', '.join(header)!r}, not the expected {spec['expect']!r}")
        sub = f"{name}  ·  {f'row {first}' if first == last else f'rows {first}–{last}'}{at_ref}"
    else:
        if "lines" not in spec:
            raise StoryboardError(f'{name}: a chart from a table in a document takes "lines": [first, last] around the table')
        first, last = spec["lines"]
        where = f"{name}:{first}-{last}"
        in_tex = name.lower().endswith((".tex", ".ltx"))
        header, _, rows, first_line = (source.tex_table if in_tex else source.md_table)(
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
        if value in header:
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
        series.append({"name": header[yi], "values": values, "texts": [row[yi] for row in rows]})
        units.append(next(iter(unit), ""))
    if len(set(units)) > 1:
        raise StoryboardError(f"{where}: the columns are in different units ({', '.join(repr(u) for u in units)}), and one "
                              "axis cannot measure both; draw them in two chart scenes")
    numbers = [v for s in series for v in s["values"] if v is not None]
    low, high = min(numbers), max(numbers)
    if kind == "bar" or 0 <= low <= 0.6 * high or high <= 0 <= low:
        low, high = min(low, 0.0), max(high, 0.0)          # bars are lengths, so they are measured from zero
    if high == low:
        high = low + 1.0
    import math
    marks = plot.ticks(low, high, 5)                   # the axis runs between round numbers that take in every value
    step = marks[1] - marks[0] if len(marks) > 1 else high - low
    bottom, top = math.floor(low / step + 1e-9) * step, math.ceil(high / step - 1e-9) * step
    marks = plot.ticks(bottom, top, max(1, round((top - bottom) / step)))
    axis = {"min": bottom, "max": top, "ticks": [[v, plot.minus(plot.number(v))] for v in marks],
            "title": _titled(header[ys[0]] if len(ys) == 1 else "", units[0])}

    labels = [row[xi] for row in rows]
    payload: dict = {"chart": kind, "labels": labels, "series": series, "axis": axis}
    if kind == "line":
        positions = None
        try:
            got = [reading(text) for text in labels]
            if all(g is not None for g in got) and all(a[0] < z[0] for a, z in zip(got, got[1:])):
                positions = [g[0] for g in got]
        except ValueError:
            pass
        if positions:
            x_marks = [v for v in plot.ticks(positions[0], positions[-1], 6)]
            payload["x"] = {"numeric": True, "at": positions, "min": positions[0], "max": positions[-1],
                            "ticks": [[v, plot.minus(plot.number(v))] for v in x_marks], "title": header[xi]}
        else:                                           # names or dates: evenly spaced, in the file's order
            show = max(1, -(-len(labels) // 8))
            payload["x"] = {"numeric": False, "at": list(range(len(labels))), "min": 0, "max": len(labels) - 1,
                            "ticks": [[i, labels[i]] for i in range(0, len(labels), show)], "title": header[xi]}
    for text in labels if kind == "bar" else []:
        if len(text) > 28:
            b.warn(where, f"the name {text[:24]!r}... is over 28 characters and will be cut on the chart")

    columns = ", ".join(header[i] for i in ys)
    scene = b.scene("chart", kicker, {**spec, "sub": f"{sub}  ·  {columns} by {header[xi]}"}, sub_is_source=True, **payload)
    scene.sfx.append((0.0, "whoosh"))
    ops = scene.payload["ops"]

    def spot(item, what: str) -> dict:
        if not isinstance(item, dict):
            raise StoryboardError(f'{where}: {what} takes an object such as {{"x": "{labels[0]}"}}, or a list of them; not {item!r}')
        plan._only(item, {"x", "row", "series", "as"}, f'"{what}"', where)
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
        if "series" in item:
            names = [x["name"] for x in series]
            if item["series"] not in names:
                raise StoryboardError(f"{where}: {what} names the column {item['series']!r}; the chart draws {', '.join(names)}")
            s = names.index(item["series"])
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
                        named[str(item["as"])] = at

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

        beat = {**beat, **{k: quoted(beat[k]) for k in ("say", "speak") if k in beat}}
        for t, act, src in clock.beat(beat):
            if "reveal" in act:
                stage.upto(act["reveal"], t)
            if "highlight" in act:
                given = act["highlight"]
                target = [] if given is None else [spot(i, "highlight") for i in (given if isinstance(given, list) else [given])]
            else:
                target = [] if src is beat else lit
            if target != lit:
                ops.append({"op": "highlight", "t": round(t + 0.05, 3), "cells": target})
                if target:
                    scene.sfx.append((round(t + 0.05, 3), "tick"))
                lit = target
    stage.upto(len(series), clock.t)
    clock.finish()
    return scene
