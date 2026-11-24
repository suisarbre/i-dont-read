"""Three scenes for how code is put together and how it runs: a diagram with branches, a row of cells that
changes step by step, and a sequence of messages between parties.

Like a graph in plot.py, each is worked out here and not typed: where a node sits, what a row of cells holds
after an operation, which arrow a beat walks along. What cannot be right is refused with its reason: an arrow
to a node that does not exist, a pop from an empty row, a step along an arrow that was never drawn.
"""
from __future__ import annotations

from . import plan
from .plan import StoryboardError

# --- a diagram with branches ---------------------------------------------------------------------

MAX_NODES = 10
# How many layers a diagram may have along its direction, and how many nodes side by side, per format.
ROOM = {("wide", "right"): (6, 4), ("wide", "down"): (4, 6), ("tall", "down"): (7, 3), ("tall", "right"): (3, 7)}


def layout(ids: list[str], edges: list[tuple[str, str]]) -> dict:
    """Place the nodes of a directed graph in layers, the way such diagrams are drawn by hand: every arrow
    points forward where it can, an arrow that closes a loop points back, and arrows cross as little as a few
    sweeps of sorting can manage.

    Returns {"layers", "across", "nodes": {id: (layer, slot)}, "routes": [[(layer, slot), ...] per edge],
    "back": [bool per edge]}. A route runs from its edge's "from" to its "to"; a slot is a position across the
    layer, centred on zero. An arrow from a node to itself has a route of one point."""
    order = {n: i for i, n in enumerate(ids)}
    out: dict[str, list[str]] = {n: [] for n in ids}
    for a, z in edges:
        if a != z and z not in out[a]:
            out[a].append(z)
    # An arrow back to a node still being explored closes a loop: draw it backwards, lay it out forwards.
    state, back = {}, set()

    def visit(n: str) -> None:
        state[n] = "open"
        for m in out[n]:
            if state.get(m) == "open":
                back.add((n, m))
            elif m not in state:
                visit(m)
        state[n] = "done"

    for n in ids:
        if n not in state:
            visit(n)
    forward = {n: [m for m in out[n] if (n, m) not in back] for n in ids}
    for a, z in back:
        if a not in forward[z]:
            forward[z].append(a)
    layer: dict[str, int] = {}

    def depth(n: str) -> int:
        if n not in layer:
            layer[n] = 0
            layer[n] = max((depth(p) + 1 for p in ids if n in forward[p]), default=0)
        return layer[n]

    for n in ids:
        depth(n)
    count = max(layer.values()) + 1
    rows: list[list] = [[] for _ in range(count)]
    for n in ids:
        rows[layer[n]].append(n)
    # An arrow that spans several layers gets a waypoint in each layer between, so nothing is drawn through it.
    chains = []
    for k, (a, z) in enumerate(edges):
        if a == z:
            chains.append([a])
            continue
        lo, hi = (z, a) if (a, z) in back else (a, z)
        chain = [lo]
        for step in range(layer[lo] + 1, layer[hi]):
            point = ("waypoint", k, step)
            rows[step].append(point)
            chain.append(point)
        chain.append(hi)
        chains.append(chain)
    links = [(p, q) for chain in chains for p, q in zip(chain, chain[1:])]

    def crossings() -> int:
        at = {n: i for row in rows for i, n in enumerate(row)}
        level = {n: i for i, row in enumerate(rows) for n in row}
        total = 0
        for i in range(count - 1):
            here = sorted((at[p], at[q]) for p, q in links if level[p] == i)
            total += sum(1 for x in range(len(here)) for y in range(x + 1, len(here))
                         if here[x][0] < here[y][0] and here[x][1] > here[y][1])
        return total

    def sweep(down: bool) -> None:
        for i in (range(1, count) if down else range(count - 2, -1, -1)):
            other = {n: j for j, n in enumerate(rows[i - 1 if down else i + 1])}
            def middle(n):
                near = [other[q if p == n else p] for p, q in links if n in (p, q) and (q if p == n else p) in other]
                return sum(near) / len(near) if near else rows[i].index(n)
            keys = {n: middle(n) for n in rows[i]}
            rows[i].sort(key=lambda n: (keys[n], order.get(n, MAX_NODES) if isinstance(n, str) else MAX_NODES))

    best, least = [list(r) for r in rows], crossings()
    for turn in range(6):
        sweep(turn % 2 == 0)
        now = crossings()
        if now < least:
            best, least = [list(r) for r in rows], now
    rows = best
    slot = {n: i - (len(row) - 1) / 2 for row in rows for i, n in enumerate(row)}
    level = {n: i for i, row in enumerate(rows) for n in row}
    routes = []
    for (a, z), chain in zip(edges, chains):
        points = [(level[n], slot[n]) for n in chain]
        routes.append(points[::-1] if (a, z) in back else points)
    return {"layers": count, "across": max(len(r) for r in rows), "nodes": {n: (layer[n], slot[n]) for n in ids},
            "routes": routes, "back": [(a, z) in back for a, z in edges]}


def _diagram(b, spec: dict, kicker: str) -> plan.Scene:
    where = spec.get("heading") or "diagram"
    plan._only(spec, {"type", "heading", "sub", "beyond", "math", "beats", "nodes", "edges", "direction"}, "a diagram scene", where)
    nodes, edges = spec["nodes"], spec.get("edges") or []
    if not 2 <= len(nodes) <= MAX_NODES:
        raise StoryboardError(f"{where}: a diagram shows 2 to {MAX_NODES} nodes, not {len(nodes)}; split it into two scenes")
    ids = []
    for node in nodes:
        if not isinstance(node, dict) or not node.get("label"):
            raise StoryboardError(f'{where}: a node is an object such as {{"id": "parse", "label": "Parse"}}, not {node!r}')
        plan._only(node, {"id", "label", "desc"}, "a node", where)
        ids.append(str(node.get("id") or node["label"]))
    for name in ids:
        if ids.count(name) > 1:
            raise StoryboardError(f'{where}: two nodes are called {name!r}; give each its own "id"')

    def known(name, what: str) -> str:
        if str(name) not in ids:
            raise StoryboardError(f"{where}: {what} names {name!r}, which is not a node; the nodes are {', '.join(ids)}")
        return str(name)

    pairs = []
    for edge in edges:
        if not isinstance(edge, dict) or "from" not in edge or "to" not in edge:
            raise StoryboardError(f'{where}: an edge is an object such as {{"from": "a", "to": "b", "label": "on error"}}, not {edge!r}')
        plan._only(edge, {"from", "to", "label", "dashed"}, "an edge", where)
        pair = (known(edge["from"], "an edge"), known(edge["to"], "an edge"))
        if pair in pairs:
            raise StoryboardError(f"{where}: the edge from {pair[0]!r} to {pair[1]!r} is listed twice")
        pairs.append(pair)
        if len(str(edge.get("label") or "")) > 18:
            b.warn(where, f"edge label {edge['label']!r} is over 18 characters; it sits on the arrow, so keep it to a word or two")
    direction = spec.get("direction") or ("down" if b.fmt == "tall" else "right")
    if direction not in ("right", "down"):
        raise StoryboardError(f'{where}: "direction" is "right" or "down", not {direction!r}')
    placed = layout(ids, pairs)
    deep, wide = ROOM[(b.fmt, direction)]
    if placed["layers"] > deep or placed["across"] > wide:
        other = "down" if direction == "right" else "right"
        fits = placed["layers"] <= ROOM[(b.fmt, other)][0] and placed["across"] <= ROOM[(b.fmt, other)][1]
        raise StoryboardError(
            f"{where}: this diagram is {placed['layers']} steps long and {placed['across']} wide, and a {b.fmt} frame "
            f"drawn {direction}wards has room for {deep} by {wide}; "
            + (f'add "direction": "{other}"' if fits else "show part of it, or split it into two scenes"))
    limit = 14 if placed["layers"] >= 5 and direction == "right" else 20
    for node in nodes:
        if len(node["label"]) > limit:
            b.warn(where, f"node label {node['label']!r} is over {limit} characters and may wrap")
    on = plan._math_on(b, spec)
    scene = b.scene("diagram", kicker, spec, direction=direction, layers=placed["layers"], across=placed["across"],
                    nodes=[{"id": name, "label": b.rich(node["label"], on, where), "desc": b.rich(node.get("desc"), on, where),
                            "at": list(placed["nodes"][name])} for name, node in zip(ids, nodes)],
                    edges=[{"from": ids.index(a), "to": ids.index(z), "label": edge.get("label"),
                            "dashed": bool(edge.get("dashed")), "route": [list(p) for p in route], "back": back}
                           for (a, z), edge, route, back in zip(pairs, edges, placed["routes"], placed["back"])])
    scene.sfx.append((0.0, "whoosh"))
    ops = scene.payload["ops"]
    clock = plan._Clock(b, scene, where)
    stage = plan._Stage(scene, len(ids), "node", plan._staged(spec))
    focused, walked = [], []
    for beat in spec.get("beats", []):
        for t, act, src in clock.beat(beat):
            if "reveal" in act:
                stage.upto(act["reveal"], t)
            if "focus" in act:
                given = act["focus"]
                target = [] if given is None else [ids.index(known(n, '"focus"')) for n in (given if isinstance(given, list) else [given])]
            else:
                target = [] if src is beat else focused          # a new sentence with no focus drops the ring
            if target != focused:
                ops.append({"op": "focus", "t": round(t + 0.05, 3), "nodes": target})
                focused = target
            if "follow" in act:
                given = act["follow"]
                steps = [] if given is None else (given if given and isinstance(given[0], list) else [given])
                path = []
                for step in steps:
                    if not (isinstance(step, list) and len(step) == 2):
                        raise StoryboardError(f'{where}: "follow" is an edge written ["from", "to"], or a list of them; not {step!r}')
                    pair = (known(step[0], '"follow"'), known(step[1], '"follow"'))
                    if pair not in pairs:
                        raise StoryboardError(f"{where}: \"follow\" walks from {pair[0]!r} to {pair[1]!r}, but there is no "
                                              "edge that way; add it to \"edges\" or follow one that is there")
                    path.append(pairs.index(pair))
            else:
                path = [] if src is beat else walked
            if path != walked:
                ops.append({"op": "follow", "t": round(t + 0.05, 3), "edges": path})
                if path:
                    scene.sfx.append((round(t + 0.05, 3), "tick"))
                walked = path
    stage.upto(len(ids), clock.t)
    # An arrow is drawn once both its ends are there.
    seen = {op["node"]: op["t"] for op in ops if op["op"] == "reveal"}
    for k, edge in enumerate(scene.payload["edges"]):
        ops.append({"op": "edge", "t": round(max(seen[edge["from"]], seen[edge["to"]]) + 0.12, 3), "edge": k})
    first = min(seen.values(), default=0.0)
    if first > plan.LEAD + 1.0:
        b.warn(where, f"nothing is on screen for the first {first:.1f} seconds; reveal the first node when the first sentence starts")
    clock.finish()
    return scene


# --- a row of cells that changes -----------------------------------------------------------------

MAX_CELLS = {"wide": 12, "tall": 7}
_VERBS = ("push", "pop", "remove", "insert", "move", "swap", "set")
_VERB_FIELDS = {"push": {"push", "at"}, "pop": {"pop"}, "remove": {"remove"}, "insert": {"insert", "at"},
                "move": {"move", "to"}, "swap": {"swap"}, "set": {"set", "to"}}


def _array(b, spec: dict, kicker: str) -> plan.Scene:
    where = spec.get("heading") or "array"
    plan._only(spec, {"type", "heading", "sub", "beyond", "math", "beats", "items", "capacity", "index", "ends"}, "an array scene", where)
    room = MAX_CELLS[b.fmt]

    def text(value) -> str:
        if isinstance(value, bool) or not isinstance(value, (str, int, float)):
            raise StoryboardError(f"{where}: a cell holds a short text or a number, not {value!r}")
        shown = str(value)
        if not shown.strip() or len(shown) > 14:
            raise StoryboardError(f"{where}: a cell holds 1 to 14 characters, not {shown!r}")
        return shown

    capacity = spec.get("capacity")
    if capacity is not None and (isinstance(capacity, bool) or not isinstance(capacity, int) or not 1 <= capacity <= room):
        raise StoryboardError(f'{where}: "capacity" is how many cells the row can hold, a whole number from 1 to {room}')
    ends = spec.get("ends") or {}
    plan._only(ends, {"front", "back"}, '"ends"', where)
    cells = [{"id": i, "text": text(v)} for i, v in enumerate(spec.get("items") or [])]     # every cell that ever exists
    row = [c["id"] for c in cells]                                                             # the row now, front first
    most = len(row)

    def full_check() -> None:
        limit = capacity or room
        if len(row) > limit:
            raise StoryboardError(f"{where}: the row would hold {len(row)} cells, and " + (
                f'its "capacity" is {capacity}: remove one first' if capacity else
                f"a {b.fmt} frame has room for {room}: show fewer, or split the scene"))

    full_check()

    def name(i: int) -> str:
        return cells[row[i]]["text"]

    def place(given, what: str, extra: int = 0) -> int:
        """An index into the row: a number from 0, "front", "back", or {"value": text} for the one cell that holds it."""
        size = len(row) + extra
        if given == "front":
            return 0
        if given == "back":
            return size - 1
        if isinstance(given, dict) and set(given) == {"value"}:
            hits = [i for i in range(len(row)) if name(i) == str(given["value"])]
            if len(hits) != 1:
                raise StoryboardError(f"{where}: {what} looks for the cell holding {str(given['value'])!r}, and "
                                      f"{'none does' if not hits else f'{len(hits)} do; give its index instead'}. "
                                      f"The row is [{', '.join(name(i) for i in range(len(row)))}]")
            return hits[0]
        if isinstance(given, bool) or not isinstance(given, int):
            raise StoryboardError(f'{where}: {what} is an index from 0, "front", "back" or {{"value": "text"}}, not {given!r}')
        if not 0 <= given < size:
            raise StoryboardError(f"{where}: {what} is index {given}, but the row has "
                                  + (f"indices 0 to {size - 1}" if size else "nothing in it")
                                  + f" at that point: [{', '.join(name(i) for i in range(len(row)))}]")
        return given

    def apply(op: dict) -> dict:
        """Carry out one operation on the row. Returns what the player has to show for it."""
        nonlocal most
        verbs = [v for v in _VERBS if v in op]
        if len(verbs) != 1:
            raise StoryboardError(f'{where}: an operation is one of {", ".join(_VERBS)}, as in {{"push": "d"}}; not {op!r}')
        verb = verbs[0]
        plan._only(op, _VERB_FIELDS[verb], f'"{verb}"', where)
        change: dict = {"verb": verb}
        if verb in ("push", "insert"):
            if verb == "push":
                if op.get("at", "back") not in ("front", "back"):
                    raise StoryboardError(f'{where}: "push" adds at the "back" (or "at": "front"); to put a cell '
                                          'at an index, use {"insert": "x", "at": 2}')
                at = len(row) if op.get("at", "back") == "back" else 0
            else:
                if "at" not in op:
                    raise StoryboardError(f'{where}: "insert" needs "at": the index the new cell takes, as in {{"insert": "x", "at": 2}}')
                at = place(op["at"], '"insert": "at"', extra=1)
            cells.append({"id": len(cells), "text": text(op[verb])})
            row.insert(at, cells[-1]["id"])
            full_check()
            change["enter"] = cells[-1]["id"]
        elif verb in ("pop", "remove"):
            if not row:
                raise StoryboardError(f'{where}: "{verb}" takes a cell out, but the row is empty at that point')
            change["leave"] = row.pop(place(op[verb], f'"{verb}"'))
        elif verb == "move":
            if "to" not in op:
                raise StoryboardError(f'{where}: "move" needs "to": where the cell goes, as in {{"move": 1, "to": "back"}}')
            cell = row.pop(place(op["move"], '"move"'))
            row.insert(place(op["to"], '"move": "to"', extra=1), cell)
            change["moved"] = [cell]
        elif verb == "swap":
            pair = op["swap"]
            if not (isinstance(pair, list) and len(pair) == 2):
                raise StoryboardError(f'{where}: "swap" takes two places, as in {{"swap": [0, 3]}}; not {pair!r}')
            i, j = place(pair[0], '"swap"'), place(pair[1], '"swap"')
            if i == j:
                raise StoryboardError(f'{where}: "swap" needs two different cells')
            row[i], row[j] = row[j], row[i]
            change["moved"] = [row[i], row[j]]
        else:
            if "to" not in op:
                raise StoryboardError(f'{where}: "set" needs "to": the new content, as in {{"set": 1, "to": "z"}}')
            cell = row[place(op["set"], '"set"')]
            cells.append({"id": len(cells), "text": text(op["to"])})      # the new content is a new cell in the old one's place
            row[row.index(cell)] = cells[-1]["id"]
            change["leave"], change["enter"] = cell, cells[-1]["id"]
        most = max(most, len(row))
        change["row"] = list(row)
        return change

    scene = b.scene("array", kicker, spec, start=list(row), capacity=capacity, index=bool(spec.get("index", True)),
                    ends={k: str(v) for k, v in ends.items()})
    scene.sfx.append((0.0, "whoosh"))
    ops = scene.payload["ops"]
    clock = plan._Clock(b, scene, where)
    marked, pointed = [], {}
    for beat in spec.get("beats", []):
        for t, act, src in clock.beat(beat):
            did = False
            if "do" in act:
                given = act["do"] if isinstance(act["do"], list) else [act["do"]]
                for j, op in enumerate(given):
                    if not isinstance(op, dict):
                        raise StoryboardError(f'{where}: "do" takes an operation such as {{"push": "d"}}, or a list of them; not {op!r}')
                    at = round(t + 0.05 + j * 0.7, 3)
                    ops.append({"op": "change", "t": at, **apply(op)})
                    scene.sfx.append((at, "pop" if "enter" in ops[-1] else "tick"))
                    did = True
                clock.t = max(clock.t, at + 0.8 + plan.GAP)            # the last move has landed before the next sentence
            # Marks and pointers are about the row as it stands; an operation, or a new sentence, clears them.
            if "mark" in act:
                given = act["mark"]
                target = [] if given is None else [row[place(g, '"mark"')] for g in (given if isinstance(given, list) else [given])]
            else:
                target = [] if (src is beat or did) else marked
            if target != marked:
                ops.append({"op": "mark", "t": round(t + (0.75 if did else 0.05), 3), "cells": target})
                marked = target
            if "pointers" in act:
                given = act["pointers"] or {}
                if not isinstance(given, dict) or len(given) > 3:
                    raise StoryboardError(f'{where}: "pointers" names up to 3 places, as in {{"i": 0, "j": 3}}; not {given!r}')
                names = {}
                for label, at_ in given.items():
                    if not 1 <= len(str(label)) <= 8:
                        raise StoryboardError(f"{where}: a pointer's name is 1 to 8 characters, not {label!r}")
                    names[str(label)] = row[place(at_, f'pointer "{label}"')]
            else:
                names = {} if (src is beat or did) else pointed
            if names != pointed:
                ops.append({"op": "pointers", "t": round(t + (0.75 if did else 0.05), 3), "at": names})
                pointed = names
    clock.finish()
    on = plan._math_on(b, spec)
    scene.payload["cells"] = [{"id": c["id"], "text": b.rich(c["text"], on, where)} for c in cells]
    scene.payload["most"] = max(most, capacity or 0, 1)
    scene.payload["longest"] = max((len(c["text"]) for c in cells), default=1)
    return scene


# --- a sequence of messages ----------------------------------------------------------------------

MAX_ACTORS = {"wide": 5, "tall": 4}
MAX_MESSAGES = {"wide": 9, "tall": 14}


def _sequence(b, spec: dict, kicker: str) -> plan.Scene:
    where = spec.get("heading") or "sequence"
    plan._only(spec, {"type", "heading", "sub", "beyond", "math", "beats", "actors", "messages"}, "a sequence scene", where)
    actors = [str(a) for a in spec["actors"]]
    if not 2 <= len(actors) <= MAX_ACTORS[b.fmt]:
        raise StoryboardError(f"{where}: a sequence has 2 to {MAX_ACTORS[b.fmt]} parties in a {b.fmt} frame, not {len(actors)}")
    for name in actors:
        if actors.count(name) > 1:
            raise StoryboardError(f"{where}: two parties are called {name!r}")
        if len(name) > 16:
            b.warn(where, f"the name {name!r} is over 16 characters and may not fit above its line")
    messages = spec["messages"]
    if not 1 <= len(messages) <= MAX_MESSAGES[b.fmt]:
        raise StoryboardError(f"{where}: a sequence shows 1 to {MAX_MESSAGES[b.fmt]} messages in a {b.fmt} frame, not "
                              f"{len(messages)}; split it into two scenes")
    on = plan._math_on(b, spec)
    rows = []
    for n, m in enumerate(messages, 1):
        if not isinstance(m, dict) or "from" not in m or "to" not in m or not m.get("label"):
            raise StoryboardError(f'{where}: message {n} needs "from", "to" and "label", as in '
                                  f'{{"from": "{actors[0]}", "to": "{actors[1]}", "label": "request"}}; not {m!r}')
        plan._only(m, {"from", "to", "label", "reply"}, "a message", where)
        for end in ("from", "to"):
            if str(m[end]) not in actors:
                raise StoryboardError(f"{where}: message {n} names {m[end]!r}, which is not one of the parties: {', '.join(actors)}")
        span = abs(actors.index(str(m["from"])) - actors.index(str(m["to"])))
        if len(m["label"]) > (24 if span == 0 else 22 + 16 * (span - 1)):
            b.warn(where, f"message {n}, {m['label'][:24]!r}..., is long for the space between its two parties and may be cut")
        rows.append({"from": actors.index(str(m["from"])), "to": actors.index(str(m["to"])),
                     "label": b.rich(m["label"], on, where), "reply": bool(m.get("reply"))})
    scene = b.scene("sequence", kicker, spec, actors=actors, messages=rows)
    scene.sfx.append((0.0, "whoosh"))
    clock = plan._Clock(b, scene, where)
    stage = plan._Stage(scene, len(rows), "message", plan._staged(spec))
    focused = None
    for beat in spec.get("beats", []):
        for t, act, src in clock.beat(beat):
            if "reveal" in act:
                stage.upto(act["reveal"], t)
            if "focus" in act:
                target = None if act["focus"] is None else int(act["focus"]) - 1
                if target is not None and not 0 <= target < len(rows):
                    raise StoryboardError(f"{where}: focus {target + 1} is not one of the {len(rows)} messages")
            else:
                target = None if src is beat else focused
            if target != focused:
                scene.payload["ops"].append({"op": "focus", "t": round(t + 0.05, 3), "message": target})
                focused = target
    stage.upto(len(rows), clock.t)
    first = min((op["t"] for op in scene.payload["ops"] if op["op"] == "reveal"), default=0.0)
    if first > plan.LEAD + 1.0:
        b.warn(where, f"nothing is on screen for the first {first:.1f} seconds; reveal the first message when the first sentence starts")
    clock.finish()
    return scene
