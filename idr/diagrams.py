"""Three scenes for how code is put together and how it runs: a diagram with branches, a row of cells that
changes step by step, and a sequence of messages between parties.

Like a graph in plot.py, each is worked out here and not typed: where a node sits, what a row of cells holds
after an operation, which arrow a beat walks along. What cannot be right is refused with its reason: an arrow
to a node that does not exist, a pop from an empty row, a step along an arrow that was never drawn.
"""
from __future__ import annotations

from . import plan
from .plan import StoryboardError

def _words(value, what: str, where: str, needed: bool = True) -> str | None:
    """A piece of text for the screen: a string with something in it. Anything else would be filmed as it is
    ("[object Object]", an empty box), so it is refused here."""
    if value is None and not needed:
        return None
    if not isinstance(value, str) or not value.strip():
        raise StoryboardError(f"{where}: {what} is a piece of text, not {value!r}")
    return " ".join(value.split())


def _beats(spec: dict, what: str, where: str) -> None:
    if not isinstance(spec.get("beats"), list) or not spec["beats"]:
        raise StoryboardError(f"{where}: {what} needs at least one beat: a sentence about what it shows")


def _flag(item: dict, key: str, what: str, where: str) -> bool:
    if not isinstance(item.get(key, False), bool):
        raise StoryboardError(f'{where}: "{key}" on {what} is true or false, not {item[key]!r}')
    return item.get(key, False)


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
    if not isinstance(spec["nodes"], list) or not isinstance(spec.get("edges") or [], list):
        raise StoryboardError(f'{where}: "nodes" and "edges" are lists of objects')
    nodes, edges = ([dict(x) if isinstance(x, dict) else x for x in given] for given in (spec["nodes"], spec.get("edges") or []))
    _beats(spec, "a diagram", where)
    if not 2 <= len(nodes) <= MAX_NODES:
        raise StoryboardError(f"{where}: a diagram shows 2 to {MAX_NODES} nodes, not {len(nodes)}; "
                              + ("split it into two scenes" if len(nodes) > MAX_NODES else
                                 "one thing alone is not a diagram: add what it connects to, or say it in another scene"))
    ids = []
    for node in nodes:
        if not isinstance(node, dict) or "label" not in node:
            raise StoryboardError(f'{where}: a node is an object such as {{"id": "parse", "label": "Parse"}}, not {node!r}')
        plan._only(node, {"id", "label", "desc"}, "a node", where)
        node["label"] = _words(node["label"], "a node's label", where)
        node["desc"] = _words(node.get("desc"), f"the \"desc\" of {node['label']!r}", where, needed=False)
        if len(node["desc"] or "") > 36:
            b.warn(where, f"the \"desc\" of {node['label']!r} is {len(node['desc'])} characters; it is small print "
                   "under the label, so keep it under 36 or it will be too small to read")
        if "id" in node and (isinstance(node["id"], bool) or not isinstance(node["id"], (str, int)) or not str(node["id"]).strip()):
            raise StoryboardError(f"{where}: the \"id\" of {node['label']!r} is a short name, not {node['id']!r}")
        ids.append(str(node["id"]).strip() if "id" in node else node["label"])
    for name in ids:
        if ids.count(name) > 1:
            raise StoryboardError(f'{where}: two nodes are called {name!r}; give each its own "id"')

    def known(name, what: str) -> str:
        if isinstance(name, bool) or not isinstance(name, (str, int)) or str(name).strip() not in ids:
            raise StoryboardError(f"{where}: {what} names {name!r}, which is not a node; the nodes are {', '.join(ids)}")
        return str(name).strip()

    pairs = []
    for edge in edges:
        if not isinstance(edge, dict) or "from" not in edge or "to" not in edge:
            raise StoryboardError(f'{where}: an edge is an object such as {{"from": "a", "to": "b", "label": "on error"}}, not {edge!r}')
        plan._only(edge, {"from", "to", "label", "dashed"}, "an edge", where)
        pair = (known(edge["from"], "an edge"), known(edge["to"], "an edge"))
        if pair in pairs:
            raise StoryboardError(f"{where}: the edge from {pair[0]!r} to {pair[1]!r} is listed twice")
        pairs.append(pair)
        edge["label"] = _words(edge.get("label"), f"the label of the edge from {pair[0]!r} to {pair[1]!r}", where, needed=False)
        _flag(edge, "dashed", "an edge", where)
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
        most = max(sum(1 for at in placed["nodes"].values() if at[0] == k) for k in range(placed["layers"]))
        passing = (f" (a layer holds at most {most} node{'s' * (most != 1)}; the rest of the width is arrows that "
                   "pass a layer on their way to a later one)") if placed["across"] > most else ""
        raise StoryboardError(
            f"{where}: this diagram is {placed['layers']} step{'s' * (placed['layers'] != 1)} long and {placed['across']} "
            f"wide{passing}, and a {b.fmt} frame drawn {direction}wards has room for {deep} by {wide}; "
            + (f'{"change" if spec.get("direction") else "add"} "direction"{" to" if spec.get("direction") else ":"} "{other}"'
               if fits else "show part of it, or split it into two scenes"))
    limit = 14 if placed["layers"] >= 5 and direction == "right" else 20
    for node in nodes:
        if len(node["label"]) > limit:
            b.warn(where, f"node label {node['label']!r} is over {limit} characters and may wrap")
    on = plan._math_on(b, spec)
    scene = b.scene("diagram", kicker, spec, direction=direction, layers=placed["layers"], across=placed["across"],
                    nodes=[{"id": name, "label": b.rich(node["label"], on, where), "desc": b.rich(node.get("desc"), on, where),
                            "at": list(placed["nodes"][name])} for name, node in zip(ids, nodes)],
                    edges=[{"from": ids.index(a), "to": ids.index(z), "label": b.rich(edge.get("label"), on, where),
                            "dashed": bool(edge.get("dashed")), "route": [list(p) for p in route], "back": back}
                           for (a, z), edge, route, back in zip(pairs, edges, placed["routes"], placed["back"])])
    scene.sfx.append((0.0, "whoosh"))
    ops = scene.payload["ops"]
    clock = plan._Clock(b, scene, where)
    stage = plan._Stage(scene, len(ids), "node", plan._staged(spec))
    focused, walked = [], []

    def on_screen(i: int, what: str) -> None:
        if i >= stage.visible:
            raise StoryboardError(f"{where}: {what} names {ids[i]!r}, which is not on screen yet: the beats have revealed "
                                  f'{stage.visible} of the {len(ids)} nodes by then. Reveal it in the same beat ("reveal": {i + 1}) or earlier')

    for beat in spec.get("beats", []):
        acts = clock.beat(beat)
        if beat.get("at") and (focused or walked):        # the last sentence's ring and path end when this sentence starts
            start = round(clock.started + 0.05, 3)
            ops.extend(op for op in ({"op": "focus", "t": start, "nodes": []} if focused else None,
                                     {"op": "follow", "t": start, "edges": []} if walked else None) if op)
            focused, walked = [], []
        for t, act, src in acts:
            if "reveal" in act:
                stage.upto(act["reveal"], t)
            if "focus" in act:
                given = act["focus"]
                target = [] if given is None else [ids.index(known(n, '"focus"')) for n in (given if isinstance(given, list) else [given])]
                for i in target:
                    on_screen(i, '"focus"')
            else:
                target = [] if src is beat else focused          # a new sentence with no focus drops the ring
            if target != focused:
                ops.append({"op": "focus", "t": round(t + 0.05, 3), "nodes": target})
                focused = target
            if "follow" in act:
                given = act["follow"]
                if given is not None and not isinstance(given, list):
                    raise StoryboardError(f'{where}: "follow" is an edge written ["from", "to"], or a list of them; not {given!r}')
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
                    for end in pair:
                        on_screen(ids.index(end), '"follow"')
            else:
                path = [] if src is beat else walked
            if path != walked:
                ops.append({"op": "follow", "t": round(t + 0.05, 3), "edges": path})
                if path:
                    scene.sfx.append((round(t + 0.05, 3), "tick"))
                walked = path
    left = len(ids) - stage.visible
    if left and stage.visible:
        b.warn(where, f"the beats reveal {stage.visible} of the {len(ids)} nodes, so the other {left} appear only as the "
               "scene ends, with no sentence about them; reveal them in a beat, or leave them out")
    stage.upto(len(ids), clock.t)
    # An arrow is drawn once both its ends are there.
    seen = {op["node"]: op["t"] for op in ops if op["op"] == "reveal"}
    for k, edge in enumerate(scene.payload["edges"]):
        ops.append({"op": "edge", "t": round(max(seen[edge["from"]], seen[edge["to"]]) + 0.12, 3), "edge": k})
    first = min(seen.values(), default=0.0)
    if first > plan.LEAD + 1.0:
        b.warn(where, f"nothing is on screen for the first {first:.1f} seconds; reveal the first node when the first sentence starts")
    clock.finish(minimum=max(op["t"] for op in ops) + 0.9)      # the last arrow has been drawn before the scene ends
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
    _beats(spec, "an array scene", where)
    if not isinstance(spec.get("index", True), bool):
        raise StoryboardError(f'{where}: "index" is true or false (whether the cells are numbered), not {spec["index"]!r}')

    def text(value) -> str:
        if isinstance(value, bool) or not isinstance(value, (str, int, float)):
            raise StoryboardError(f"{where}: a cell holds a short text or a number, not {value!r}")
        shown = " ".join(str(value).split())                # "a" and "a " would be two cells that look the same
        if not shown or len(shown) > 14:
            raise StoryboardError(f"{where}: a cell holds 1 to 14 characters, not {shown!r}")
        return shown

    capacity = spec.get("capacity")
    if capacity is not None and (isinstance(capacity, bool) or not isinstance(capacity, int) or not 1 <= capacity <= room):
        raise StoryboardError(f'{where}: "capacity" is how many cells the row can hold, a whole number from 1 to {room}')
    ends = spec.get("ends") or {}
    if not isinstance(ends, dict):
        raise StoryboardError(f'{where}: "ends" names the two ends of the row, as in {{"front": "oldest", "back": "newest"}}; not {ends!r}')
    plan._only(ends, {"front", "back"}, '"ends"', where)
    ends = {k: _words(v, f'"ends": "{k}"', where) for k, v in ends.items()}
    if not isinstance(spec.get("items") or [], list):
        raise StoryboardError(f'{where}: "items" is a list of what the cells hold at the start, not {spec["items"]!r}')
    cells = [{"id": i, "text": text(v)} for i, v in enumerate(spec.get("items") or [])]     # every cell that ever exists
    row = [c["id"] for c in cells]                                                             # the row now, front first
    most = len(row)

    def full_check() -> None:
        # The frame is a hard limit. "capacity" is the limit the code keeps: a row may go past it for a moment,
        # as code that stores and then evicts does, and the cells past the last slot show that. It has to be
        # back within it by the end of the scene.
        if len(row) > room:
            raise StoryboardError(f"{where}: the row would hold {len(row)} cells, and a {b.fmt} frame has room for "
                                  f"{room}: show fewer, or split the scene")

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
            was = place(op["move"], '"move"')
            cell = row.pop(was)
            row.insert(place(op["to"], '"move": "to"', extra=1), cell)
            if row.index(cell) == was:
                raise StoryboardError(f"{where}: \"move\" would leave {cells[cell]['text']!r} where it is (index {was}); "
                                      f"the row is [{', '.join(name(i) for i in range(len(row)))}]")
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
            if text(op["to"]) == cells[cell]["text"]:
                raise StoryboardError(f"{where}: \"set\" would write {cells[cell]['text']!r} over the same text; nothing would change")
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
    free = 0.0                 # when the last operation has landed. The player replays what happens in order of
    for beat in spec.get("beats", []):     # time, so nothing may be timed before an operation worked out ahead of it.
        acts = clock.beat(beat)
        if beat.get("at") and (marked or pointed):        # the last sentence's marks end when this sentence starts
            start = round(max(clock.started + 0.05, free), 3)
            ops.extend(op for op in ({"op": "mark", "t": start, "cells": []} if marked else None,
                                     {"op": "pointers", "t": start, "at": {}} if pointed else None) if op)
            marked, pointed = [], {}
        for t, act, src in acts:
            did = False
            if "do" in act:
                given = act["do"] if isinstance(act["do"], list) else [act["do"]]
                if not given:
                    raise StoryboardError(f'{where}: "do" takes an operation such as {{"push": "d"}}, or a list of them; it is empty')
                for op in given:
                    if not isinstance(op, dict):
                        raise StoryboardError(f'{where}: "do" takes an operation such as {{"push": "d"}}, or a list of them; not {op!r}')
                    at = round(max(t + 0.05, free), 3)
                    ops.append({"op": "change", "t": at, **apply(op)})
                    scene.sfx.append((at, "pop" if "enter" in ops[-1] else "tick"))
                    free, did = at + 0.7, True
                clock.t = max(clock.t, at + 0.8 + plan.GAP)            # the last move has landed before the next sentence
            after = round(max(t + 0.05, free), 3)       # marks and pointers are placed on the row once it has settled
            # Marks and pointers are about the row as it stands; an operation, or a new sentence, clears them.
            if "mark" in act:
                given = act["mark"]
                target = [] if given is None else [row[place(g, '"mark"')] for g in (given if isinstance(given, list) else [given])]
            else:
                target = [] if (src is beat or did) else marked
            if target != marked:
                ops.append({"op": "mark", "t": after, "cells": target})
                marked = target
            if "pointers" in act:
                given = {} if act["pointers"] is None else act["pointers"]
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
                ops.append({"op": "pointers", "t": after, "at": names})
                pointed = names
            if did and (target or names):                 # placed after the operations, so held long enough to be read
                clock.t = max(clock.t, after + 1.2 + plan.GAP)
    if capacity and len(row) > capacity:
        raise StoryboardError(f"{where}: the scene ends with {len(row)} cells in a row whose \"capacity\" is {capacity}: "
                              f"[{', '.join(name(i) for i in range(len(row)))}]. A row may go past its capacity for a "
                              "moment, but something has to take a cell out again before the scene ends")
    if not cells:
        raise StoryboardError(f'{where}: the row is empty from start to end; give it "items", or a "do" that adds a cell')
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
    if not isinstance(spec["actors"], list):
        raise StoryboardError(f'{where}: "actors" is a list of the parties, left to right, not {spec["actors"]!r}')
    actors = [_words(a, "a party's name", where) for a in spec["actors"]]
    if not 2 <= len(actors) <= MAX_ACTORS[b.fmt]:
        raise StoryboardError(f"{where}: a sequence has 2 to {MAX_ACTORS[b.fmt]} parties in a {b.fmt} frame, not {len(actors)}")
    for name in actors:
        if actors.count(name) > 1:
            raise StoryboardError(f"{where}: two parties are called {name!r}")
    messages = spec["messages"]
    _beats(spec, "a sequence", where)
    if not isinstance(messages, list) or not 1 <= len(messages) <= MAX_MESSAGES[b.fmt]:
        raise StoryboardError(f"{where}: a sequence shows 1 to {MAX_MESSAGES[b.fmt]} messages in a {b.fmt} frame, not "
                              + (f"{len(messages)}; split it into two scenes" if isinstance(messages, list) and messages
                                 else "none: list them in \"messages\""))
    on = plan._math_on(b, spec)
    rows = []
    for n, m in enumerate(messages, 1):
        if not isinstance(m, dict) or "from" not in m or "to" not in m or not m.get("label"):
            raise StoryboardError(f'{where}: message {n} needs "from", "to" and "label", as in '
                                  f'{{"from": "{actors[0]}", "to": "{actors[1]}", "label": "request"}}; not {m!r}')
        plan._only(m, {"from", "to", "label", "reply"}, "a message", where)
        for end in ("from", "to"):
            if not isinstance(m[end], str) or " ".join(m[end].split()) not in actors:
                raise StoryboardError(f"{where}: message {n} names {m[end]!r}, which is not one of the parties: {', '.join(actors)}")
        ends_ = [actors.index(" ".join(m[end].split())) for end in ("from", "to")]
        rows.append({"from": ends_[0], "to": ends_[1],             # whether a label fits is measured where it is drawn
                     "label": b.rich(_words(m["label"], f"the label of message {n}", where), on, where),
                     "reply": _flag(m, "reply", "a message", where)})
    scene = b.scene("sequence", kicker, spec, actors=actors, messages=rows)
    scene.sfx.append((0.0, "whoosh"))
    clock = plan._Clock(b, scene, where)
    stage = plan._Stage(scene, len(rows), "message", plan._staged(spec))
    focused = None
    for beat in spec.get("beats", []):
        acts = clock.beat(beat)
        if beat.get("at") and focused is not None:        # the last sentence's focus ends when this sentence starts
            scene.payload["ops"].append({"op": "focus", "t": round(clock.started + 0.05, 3), "message": None})
            focused = None
        for t, act, src in acts:
            if "reveal" in act:
                stage.upto(act["reveal"], t)
            if "focus" in act:
                given = act["focus"]
                if given is not None and (isinstance(given, bool) or not isinstance(given, int) or not 1 <= given <= len(rows)):
                    raise StoryboardError(f'{where}: "focus" is the number of a message, from 1 to {len(rows)}; not {given!r}')
                target = None if given is None else given - 1
                if target is not None and target >= stage.visible:
                    raise StoryboardError(f'{where}: "focus": {given} points at a message that is not on screen yet: the beats '
                                          f'have revealed {stage.visible} of {len(rows)} by then. Reveal it in the same beat ("reveal": {given}) or earlier')
            else:
                target = None if src is beat else focused
            if target != focused:
                scene.payload["ops"].append({"op": "focus", "t": round(t + 0.05, 3), "message": target})
                focused = target
    left = len(rows) - stage.visible
    if left and stage.visible:
        b.warn(where, f"the beats reveal {stage.visible} of the {len(rows)} messages, so the other {left} appear only as "
               "the scene ends, with no sentence about them; reveal them in a beat, or leave them out")
    stage.upto(len(rows), clock.t)
    first = min((op["t"] for op in scene.payload["ops"] if op["op"] == "reveal"), default=0.0)
    if first > plan.LEAD + 1.0:
        b.warn(where, f"nothing is on screen for the first {first:.1f} seconds; reveal the first message when the first sentence starts")
    clock.finish(minimum=max(op["t"] for op in scene.payload["ops"]) + 0.9)   # the last message has been drawn before the end
    return scene
