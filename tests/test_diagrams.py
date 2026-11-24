"""Tests for the scenes that show how code is put together and how it runs (diagram, array, sequence) and for
charts drawn from the source's numbers.

Run from the repository root:  python -m unittest discover tests
"""
import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from idr import chart, diagrams, plan, source

CSV = "size,hits,rate,note\n4,2565,12.8%,cold\n8,4401,22.0%,\n16,6644,33.2%,warm\n"


def build(scene, files=None, fmt="wide"):
    with tempfile.TemporaryDirectory() as tmp:
        for name, text in (files or {}).items():
            (Path(tmp) / name).write_text(text, encoding="utf-8")
        board = {"title": "t", "chapters": [{"title": "c", "scenes": [scene]}]}
        if not files:
            board["source"] = "none"
        built, warnings = plan.build(board, Path(tmp), "light", plan.DryNarrator("no such voice"), True, fmt)
        return built[-1], warnings


def refused(test, scene, why, files=None, fmt="wide"):
    with test.assertRaises(plan.StoryboardError) as caught:
        build(scene, files, fmt)
    test.assertIn(why, str(caught.exception))


class Layout(unittest.TestCase):
    def test_arrows_point_forward_and_a_loop_goes_back(self):
        placed = diagrams.layout(list("abcd"), [("a", "b"), ("b", "c"), ("c", "d"), ("d", "a")])
        self.assertEqual([placed["nodes"][n][0] for n in "abcd"], [0, 1, 2, 3])
        self.assertEqual(placed["back"], [False, False, False, True])
        self.assertEqual(placed["routes"][3][0][0], 3)                  # the arrow back still runs from d ...
        self.assertEqual(placed["routes"][3][-1][0], 0)                 # ... to a, through the layers between
        self.assertEqual(len(placed["routes"][3]), 4)

    def test_a_branch_shares_a_layer(self):
        placed = diagrams.layout(list("abcd"), [("a", "b"), ("a", "c"), ("b", "d"), ("c", "d")])
        self.assertEqual((placed["layers"], placed["across"]), (3, 2))
        self.assertEqual(placed["nodes"]["b"][0], placed["nodes"]["c"][0])
        self.assertEqual(sorted([placed["nodes"]["b"][1], placed["nodes"]["c"][1]]), [-0.5, 0.5])

    def test_a_long_arrow_goes_round_what_lies_between(self):
        placed = diagrams.layout(list("abc"), [("a", "b"), ("b", "c"), ("a", "c")])
        route = placed["routes"][2]
        self.assertEqual([p[0] for p in route], [0, 1, 2])
        self.assertNotEqual(route[1][1], placed["nodes"]["b"][1])       # its waypoint is beside b, not on it

    def test_sorting_removes_a_crossing(self):
        placed = diagrams.layout(["a", "b", "x", "y"], [("a", "y"), ("b", "x")])
        self.assertEqual(placed["nodes"]["a"][1] < placed["nodes"]["b"][1], placed["nodes"]["y"][1] < placed["nodes"]["x"][1])

    def test_an_arrow_to_itself_is_a_loop(self):
        placed = diagrams.layout(["a", "b"], [("a", "a"), ("a", "b")])
        self.assertEqual(len(placed["routes"][0]), 1)


class Diagrams(unittest.TestCase):
    def scene(self, **fields):
        return {"type": "diagram", "heading": "h", "nodes": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}, {"label": "C"}],
                "edges": [{"from": "a", "to": "b", "label": "go"}, {"from": "b", "to": "C"}], "beats": [{"say": "one"}], **fields}

    def test_an_arrow_appears_once_both_its_ends_are_there(self):
        scene, _ = build(self.scene(beats=[{"say": "First one.", "reveal": 1}, {"say": "Then all.", "reveal": 3}]))
        ops = scene.payload["ops"]
        seen = {op["node"]: op["t"] for op in ops if op["op"] == "reveal"}
        for op in ops:
            if op["op"] == "edge":
                edge = scene.payload["edges"][op["edge"]]
                self.assertGreater(op["t"], max(seen[edge["from"]], seen[edge["to"]]))

    def test_a_beat_walks_only_arrows_that_exist(self):
        scene, _ = build(self.scene(beats=[{"say": "one", "follow": [["a", "b"], ["b", "C"]], "focus": "b"}, {"say": "two"}]))
        walks = [op for op in scene.payload["ops"] if op["op"] == "follow"]
        self.assertEqual([w["edges"] for w in walks], [[0, 1], []])               # and the next sentence drops it
        refused(self, self.scene(beats=[{"say": "one", "follow": ["b", "a"]}]), "there is no edge that way")

    def test_what_does_not_exist_is_named(self):
        refused(self, self.scene(edges=[{"from": "a", "to": "z"}]), "'z', which is not a node; the nodes are a, b, C")
        refused(self, self.scene(beats=[{"say": "one", "focus": "d"}]), '"focus" names \'d\'')
        refused(self, self.scene(nodes=[{"label": "A"}, {"label": "A"}]), "two nodes are called 'A'")
        refused(self, self.scene(edges=[{"from": "a", "to": "b"}, {"from": "a", "to": "b"}]), "listed twice")
        refused(self, self.scene(edges=[{"from": "a", "to": "b", "lable": "x"}]), 'did you mean "label"?')

    def test_one_too_long_for_the_frame_says_which_way_fits(self):
        chain = {"type": "diagram", "heading": "h", "nodes": [{"label": str(i)} for i in range(7)],
                 "edges": [{"from": str(i), "to": str(i + 1)} for i in range(6)], "beats": [{"say": "one"}]}
        refused(self, chain, "7 steps long and 1 wide")
        self.assertEqual(build(chain, fmt="tall")[0].payload["direction"], "down")
        fan = {"type": "diagram", "heading": "h", "nodes": [{"label": str(i)} for i in range(6)],
               "edges": [{"from": "0", "to": str(i)} for i in range(1, 6)], "beats": [{"say": "one"}]}
        refused(self, fan, 'add "direction": "down"')


class Arrays(unittest.TestCase):
    def rows(self, items, *ops, **fields):
        scene, _ = build({"type": "array", "heading": "h", "items": items, "beats": [{"say": "one", "do": list(ops)}], **fields})
        text = {c["id"]: c["text"] for c in scene.payload["cells"]}
        return [[text[i] for i in op["row"]] for op in scene.payload["ops"] if op["op"] == "change"]

    def test_the_engine_carries_out_each_operation(self):
        self.assertEqual(self.rows(["a", "b", "c"], {"move": {"value": "b"}, "to": "back"}, {"push": "d"}, {"pop": "front"}),
                         [["a", "c", "b"], ["a", "c", "b", "d"], ["c", "b", "d"]])
        self.assertEqual(self.rows([5, 2, 8], {"swap": [0, 1]}, {"insert": 7, "at": 1}, {"set": "back", "to": 0}, {"remove": {"value": "7"}}),
                         [["2", "5", "8"], ["2", "7", "5", "8"], ["2", "7", "5", "0"], ["2", "5", "0"]])
        self.assertEqual(self.rows(["a"], {"push": "z", "at": "front"}, {"move": "back", "to": 0}), [["z", "a"], ["a", "z"]])

    def test_a_cell_keeps_its_identity_as_it_moves(self):
        scene, _ = build({"type": "array", "heading": "h", "items": ["a", "b"], "beats": [{"say": "one", "do": {"swap": [0, 1]}}]})
        change = next(op for op in scene.payload["ops"] if op["op"] == "change")
        self.assertEqual((scene.payload["start"], change["row"], sorted(change["moved"])), ([0, 1], [1, 0], [0, 1]))

    def test_what_cannot_be_done_is_refused_with_the_row(self):
        def bad(items, op, why, **fields):
            refused(self, {"type": "array", "heading": "h", "items": items, "beats": [{"say": "one", "do": op}], **fields}, why)
        bad([], {"pop": "front"}, "the row is empty")
        bad(["a", "b"], {"pop": 2}, "is index 2, but the row has indices 0 to 1 at that point: [a, b]")
        bad(["a", "a"], {"remove": {"value": "a"}}, "2 do; give its index instead")
        bad(["a"], {"move": {"value": "q"}, "to": "back"}, "none does")
        bad(["a", "b"], {"push": "c"}, 'the scene ends with 3 cells in a row whose "capacity" is 2', capacity=2)
        bad(["a", "b"], {"move": 1, "to": "back"}, "would leave 'b' where it is")
        bad(["a", "b"], {"set": 0, "to": "a"}, "nothing would change")
        bad(["a", "b"], {"swap": [1, 1]}, "two different cells")
        bad(["a"], {"shove": "b"}, "an operation is one of push, pop")
        bad(["a"], {"push": "b", "to": "front"}, '"to" is not a field of "push"')
        bad([str(i) for i in range(12)], {"push": "x"}, "a wide frame has room for 12")

    def test_marks_and_pointers_follow_the_row(self):
        scene, _ = build({"type": "array", "heading": "h", "items": ["a", "b", "c"], "beats": [
            {"say": "one", "mark": [0, {"value": "c"}], "pointers": {"i": 0, "j": "back"}},
            {"say": "two", "do": {"swap": [0, 2]}}]})
        marks = [op["cells"] for op in scene.payload["ops"] if op["op"] == "mark"]
        points = [op["at"] for op in scene.payload["ops"] if op["op"] == "pointers"]
        self.assertEqual((marks, points), ([[0, 2], []], [{"i": 0, "j": 2}, {}]))        # an operation clears both


class Sequences(unittest.TestCase):
    def scene(self, **fields):
        return {"type": "sequence", "heading": "h", "actors": ["A", "B"],
                "messages": [{"from": "A", "to": "B", "label": "ask"}, {"from": "B", "to": "A", "label": "answer", "reply": True},
                             {"from": "A", "to": "A", "label": "think"}], "beats": [{"say": "one"}], **fields}

    def test_messages_are_between_the_parties_named(self):
        scene, _ = build(self.scene())
        self.assertEqual([(m["from"], m["to"], m["reply"]) for m in scene.payload["messages"]], [(0, 1, False), (1, 0, True), (0, 0, False)])
        refused(self, self.scene(messages=[{"from": "A", "to": "C", "label": "x"}]), "'C', which is not one of the parties: A, B")
        refused(self, self.scene(actors=["A"]), "2 to 5 parties")
        refused(self, self.scene(messages=[{"from": "A", "to": "B"}]), 'needs "from", "to" and "label"')

    def test_reveal_and_focus(self):
        scene, _ = build(self.scene(beats=[{"say": "one", "reveal": 1}, {"say": "two", "reveal": 3, "focus": 2}]))
        self.assertEqual([op["message"] for op in scene.payload["ops"] if op["op"] == "reveal"], [0, 1, 2])
        self.assertEqual([op["message"] for op in scene.payload["ops"] if op["op"] == "focus"], [1])
        refused(self, self.scene(beats=[{"say": "one", "focus": 4}]), '"focus" is the number of a message, from 1 to 3')
        refused(self, self.scene(beats=[{"say": "one", "focus": True}]), '"focus" is the number of a message')
        refused(self, self.scene(beats=[{"say": "one", "reveal": 1, "focus": 3}]), "not on screen yet")


class Charts(unittest.TestCase):
    def scene(self, **fields):
        return {"type": "chart", "heading": "h", "file": "d.csv", "rows": [1, 3], "x": "size", "y": "rate",
                "beats": [{"say": "one"}], **fields}

    def test_the_numbers_are_the_files(self):
        scene, _ = build(self.scene(), {"d.csv": CSV})
        (series,) = scene.payload["series"]
        self.assertEqual((series["values"], series["texts"]), ([12.8, 22.0, 33.2], ["12.8%", "22.0%", "33.2%"]))
        self.assertEqual(scene.payload["labels"], ["4", "8", "16"])
        self.assertEqual((scene.payload["axis"]["min"], scene.payload["axis"]["title"]), (0.0, "rate (%)"))   # bars start at zero
        self.assertGreaterEqual(scene.payload["axis"]["max"], 33.2)
        self.assertEqual(scene.payload["sub"], "d.csv  ·  rows 1–3  ·  rate by size")

    def test_a_number_cannot_be_typed_in(self):
        refused(self, {"type": "chart", "heading": "h", "x": "a", "y": "b", "beats": [{"say": "one"}]},
                "Numbers cannot be typed into a chart", {"d.csv": CSV})
        refused(self, self.scene(data=[1, 2, 3]), '"data" is not a field of a chart scene', {"d.csv": CSV})
        with tempfile.TemporaryDirectory() as tmp:                                     # and it counts as showing the source
            (Path(tmp) / "d.csv").write_text(CSV, encoding="utf-8")
            board = {"title": "t", "chapters": [{"title": "c", "scenes": [self.scene()]}]}
            plan.build(board, Path(tmp), "light", plan.DryNarrator("no such voice"))
            with self.assertRaises(plan.StoryboardError) as caught:
                plan.build({**board, "chapters": [{"title": "c", "scenes": [self.scene(beyond=True)]}]}, Path(tmp), "light",
                           plan.DryNarrator("no such voice"))
            self.assertIn("shows the source", str(caught.exception))

    def test_the_narration_quotes_the_cell(self):
        scene, _ = build(self.scene(beats=[{"say": "At size {x} it is {value}.", "highlight": {"x": "8"}}]), {"d.csv": CSV})
        self.assertEqual(scene.payload["captions"][0]["text"], "At size 8 it is 22.0%.")
        self.assertEqual([op["cells"] for op in scene.payload["ops"] if op["op"] == "highlight"], [[{"row": 1, "series": 0}]])
        scene, _ = build(self.scene(y=["hits", "rate"][:1], kind="line", beats=[
            {"say": "From {a.value} to {b.value}.", "highlight": [{"row": 1, "as": "a"}, {"row": 3, "as": "b"}]}]), {"d.csv": CSV})
        self.assertEqual(scene.payload["captions"][0]["text"], "From 2565 to 6644.")
        refused(self, self.scene(beats=[{"say": "It is {value}."}]), "highlights no cells", {"d.csv": CSV})

    def test_what_would_mislead_is_refused(self):
        refused(self, self.scene(y="note"), "'cold' is not a plain number", {"d.csv": CSV})
        refused(self, self.scene(y=["hits", "rate"]), "different units", {"d.csv": CSV})
        refused(self, self.scene(rows=[1, 2]), "mixes units", {"d.csv": "size,rate\n1,5%\n2,7 ms\n"})
        refused(self, self.scene(y="speed"), "the columns are size, hits, rate, note", {"d.csv": CSV})
        refused(self, self.scene(rows=[1, 13]), "13 rows are too many for a bar chart", {"d.csv": "size,rate\n" + "".join(f"{i},{i}\n" for i in range(13))})
        refused(self, self.scene(beats=[{"say": "one", "highlight": {"x": "5"}}]), "none is", {"d.csv": CSV})

    def test_a_line_spaces_numbers_as_numbers(self):
        scene, _ = build(self.scene(kind="line", y="hits"), {"d.csv": CSV})
        self.assertEqual((scene.payload["x"]["numeric"], scene.payload["x"]["at"]), (True, [4.0, 8.0, 16.0]))
        scene, _ = build(self.scene(kind="line", x="note", y="hits"), {"d.csv": CSV.replace("8,4401,22.0%,", "8,4401,22.0%,mild")})
        self.assertEqual((scene.payload["x"]["numeric"], scene.payload["x"]["at"]), (False, [0, 1, 2]))

    def test_reading_a_cell(self):
        for cell, got in [("12.5 ms", (12.5, "ms")), ("$1,200", (1200.0, "$")), ("−0.8", (-0.8, "")), ("3e2", (300.0, "")),
                          ("$-0.8$", (-0.8, "")), ("97.5%", (97.5, "%")), ("", None), ("n/a", None)]:
            self.assertEqual(chart.reading(cell), got)
        with self.assertRaises(ValueError):
            chart.reading("fast")

    def test_a_markdown_table_works_too(self):
        table = "Intro.\n\n| size | rate |\n|---|---|\n| 4 | 12.8% |\n| 8 | 22.0% |\n"
        scene, _ = build({"type": "chart", "heading": "h", "file": "r.md", "lines": [3, 6], "x": "size", "y": "rate",
                          "beats": [{"say": "one"}]}, {"r.md": table})
        self.assertEqual(scene.payload["series"][0]["values"], [12.8, 22.0])


class WholeCells(unittest.TestCase):
    """A chart draws a cell only when the whole of it is one number: the first digits of "1,25" or "1:45" are
    another number."""

    def test_what_is_not_one_plain_number_is_refused(self):
        for cell in ["1,25", "0,5", "1.234,56", "0:45", "1'500", "1\\,500", "2^10", "12*", "1 234", "5 ms avg", "$5 USD", "12,34"]:
            with self.assertRaises(ValueError, msg=cell):
                chart.reading(cell)
        with self.assertRaises(ValueError) as caught:
            chart.reading("1,25")
        self.assertIn("decimal comma", str(caught.exception))

    def test_a_huge_power_of_ten_is_refused_at_once(self):
        began = time.time()
        for cell in ["1e999999999", "1e400", "9e99999"]:
            with self.assertRaises(ValueError):
                chart.reading(cell)
        self.assertLess(time.time() - began, 1.0)
        refused(self, {"type": "chart", "heading": "h", "file": "d.csv", "rows": [1, 2], "x": "n", "y": "v", "beats": [{"say": "one"}]},
                "too large, too small or too close together", {"d.csv": "n,v\na,1e-320\nb,2e-320\n"})

    def test_units_in_headers_count(self):
        def scene(**fields):
            return {"type": "chart", "heading": "h", "file": "d.csv", "rows": [1, 2], "x": "n", "beats": [{"say": "one"}], **fields}
        data = {"d.csv": "n,time (ms),size (KB),p99 (ms),wait (ms),score (higher is better)\na,5,900,9,5 s,1\nb,7,300,12,6 s,2\n"}
        refused(self, scene(y=["time (ms)", "size (KB)"]), "'time (ms)' in ms, 'size (KB)' in KB", data)
        refused(self, scene(y="wait (ms)"), "says ms, and the cells under it are in s", data)
        both, _ = build(scene(y=["time (ms)", "p99 (ms)"]), data)
        self.assertEqual(both.payload["axis"]["title"], "ms")
        self.assertEqual(chart.header_unit("score (higher is better)"), "")
        self.assertEqual(chart.header_unit("rate [req/s]"), "req/s")

    def test_a_footnote_mark_stays_on_its_cell(self):
        self.assertEqual([source._cell(c) for c in [" 12* ", " *bold* ", "**x**", " a*b ", " 5† "]], ["12*", "bold", "x", "a*b", "5†"])
        refused(self, {"type": "chart", "heading": "h", "file": "r.md", "lines": [1, 4], "x": "n", "y": "v", "beats": [{"say": "one"}]},
                "'12*' is not a plain number", {"r.md": "| n | v |\n|---|---|\n| A | 12* |\n| B | 15 |\n"})


class AlongX(unittest.TestCase):
    """A line's rows are placed by their x values only when those are plain numbers; otherwise evenly."""

    def x(self, column, **fields):
        text = "x,v\n" + "".join(f"{label},{10 * (i + 1)}\n" for i, label in enumerate(column))
        scene = {"type": "chart", "heading": "h", "file": "d.csv", "rows": [1, len(column)], "x": "x", "y": "v", "kind": "line",
                 "beats": [{"say": "one"}], **fields}
        return build(scene, {"d.csv": text})[0].payload["x"]

    def test_dates_times_units_and_versions_are_names(self):
        for column in (["2019-12-31", "2020-01-01", "2024-06-30"], ["9:00", "10:45", "13:15"], ["1 KB", "2 MB", "4 GB"],
                       ["1.8", "1.9", "2.0", "2.10"], ["3", "1", "2"]):
            got = self.x(column)
            self.assertEqual((got["numeric"], got["at"], [t for _, t in got["ticks"]]), (False, list(range(len(column))), column))

    def test_numbers_are_positions_and_every_mark_reads_differently(self):
        years = self.x(["2019", "2020", "2021", "2022"])
        self.assertEqual((years["numeric"], [t for _, t in years["ticks"]]), (True, ["2019", "2020", "2021", "2022"]))
        sizes = self.x(["4 ms", "8 ms", "16 ms"])
        self.assertEqual(sizes["at"], [4.0, 8.0, 16.0])
        self.assertEqual(self.x(["2019", "2020", "2021"], spacing="even")["numeric"], False)
        with self.assertRaises(plan.StoryboardError) as caught:
            self.x(["1 KB", "2 MB", "4 GB"], spacing="numbers")
        self.assertIn("different units", str(caught.exception))

    def test_axis_marks_keep_the_digits_that_tell_them_apart(self):
        scene, _ = build({"type": "chart", "heading": "h", "file": "d.csv", "rows": [1, 3], "x": "t", "y": "v", "kind": "line",
                          "beats": [{"say": "one"}]}, {"d.csv": "t,v\n1,12345.1\n2,12345.5\n3,12345.9\n"})
        marks = [text for _, text in scene.payload["axis"]["ticks"]]
        self.assertEqual((marks[0], marks[-1], len(set(marks))), ("12345", "12346", len(marks)))
        self.assertEqual((scene.payload["axis"]["min"], scene.payload["axis"]["max"]), (12345.0, 12346.0))


class InOrder(unittest.TestCase):
    """The player replays an array's steps in order of time, so they are timed in the order they were worked out."""

    def ops(self, beat):
        scene, _ = build({"type": "array", "heading": "h", "items": ["a", "b", "c"], "beats": [beat]})
        return scene, scene.payload["ops"]

    def test_pointers_wait_for_the_last_operation(self):
        scene, ops = self.ops({"say": "Three things happen.", "do": [{"pop": "front"}, {"push": "d"}, {"push": "x", "at": "front"}],
                               "pointers": {"i": {"value": "x"}}, "mark": {"value": "d"}})
        self.assertEqual([op["op"] for op in ops], ["change", "change", "change", "mark", "pointers"])
        self.assertGreater(ops[3]["t"], ops[2]["t"] + 0.6)
        self.assertGreater(scene.duration, ops[4]["t"] + 1.0)                      # and they stay long enough to be seen

    def test_a_cue_waits_for_what_is_still_moving(self):
        _, ops = self.ops({"say": "First we push y and then z goes to the front.", "do": [{"pop": "front"}, {"push": "y"}],
                           "cues": [{"at": "push y", "do": {"push": "z", "at": "front"}}]})
        times = [op["t"] for op in ops]
        self.assertEqual(times, sorted(times))
        self.assertTrue(all(b - a >= 0.69 for a, b in zip(times, times[1:])))
        self.assertEqual([len(op["row"]) for op in ops], [2, 3, 4])               # each step shows the row after it

    def test_an_empty_do_is_refused(self):
        refused(self, {"type": "array", "heading": "h", "items": ["a"], "beats": [{"say": "one", "do": []}]}, "it is empty")
        refused(self, {"type": "array", "heading": "h", "items": "abc", "beats": [{"say": "one"}]}, '"items" is a list')


class WhatIsFilmed(unittest.TestCase):
    """Text and flags are checked for what they are, and a scene lasts until what it lists has been drawn."""

    def diagram(self, **fields):
        return {"type": "diagram", "heading": "h", "nodes": [{"label": "A"}, {"label": "B"}, {"label": "C"}],
                "edges": [{"from": "A", "to": "B"}, {"from": "B", "to": "C"}], "beats": [{"say": "one"}], **fields}

    def sequence(self, **fields):
        return {"type": "sequence", "heading": "h", "actors": ["A", "B"], "messages": [{"from": "A", "to": "B", "label": "ask"}],
                "beats": [{"say": "one"}], **fields}

    def test_a_flag_is_true_or_false(self):
        refused(self, self.diagram(edges=[{"from": "A", "to": "B", "dashed": "false"}]), '"dashed" on an edge is true or false')
        refused(self, self.sequence(messages=[{"from": "A", "to": "B", "label": "x", "reply": "no"}]), '"reply" on a message is true or false')

    def test_text_is_text(self):
        refused(self, self.diagram(nodes=[{"label": ["A"]}, {"label": "B"}]), "a node's label is a piece of text")
        refused(self, self.diagram(nodes=[{"label": "   "}, {"label": "B"}]), "a node's label is a piece of text")
        refused(self, self.diagram(edges=[{"from": "A", "to": "B", "label": {"x": 1}}]), "the label of the edge")
        refused(self, self.sequence(actors="AB"), '"actors" is a list')
        refused(self, self.sequence(actors=["A", None]), "a party's name is a piece of text")
        refused(self, self.sequence(messages=[{"from": "A", "to": "B", "label": [None]}]), "the label of message 1")

    def test_what_the_beats_leave_out_is_said_and_still_drawn(self):
        for spec, things in ((self.diagram(beats=[{"say": "one", "reveal": 1}]), "nodes"),
                             (self.sequence(messages=[{"from": "A", "to": "B", "label": str(i)} for i in range(4)],
                                            beats=[{"say": "one", "reveal": 1}]), "messages")):
            scene, warnings = build(spec)
            self.assertTrue(any(f"{things}, so the other" in w for w in warnings), warnings)
            self.assertGreaterEqual(scene.duration, max(op["t"] for op in scene.payload["ops"]) + 0.85)

    def test_a_hold_is_a_length_of_time(self):
        refused(self, self.diagram(beats=[{"hold": -5}]), '"hold" is how many seconds')
        refused(self, self.diagram(beats=[{"hold": "long"}]), '"hold" is how many seconds')


class TheSourceFolder(unittest.TestCase):
    def test_a_file_outside_it_is_not_the_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, other = Path(tmp) / "src", Path(tmp) / "other"
            root.mkdir(), other.mkdir()
            (other / "o.csv").write_text(CSV), (root / "d.csv").write_text(CSV)
            os.symlink(other / "o.csv", root / "link.csv")
            for name in ("../other/o.csv", str(other / "o.csv"), "link.csv"):
                with self.assertRaises(ValueError, msg=name) as caught:
                    source.csv_table(root, name, 1, 2)
                self.assertIn("outside the source folder", str(caught.exception))
            self.assertEqual(source.csv_table(root, "d.csv", 1, 1)[1][0][0], "4")

    def test_a_ref_is_never_an_option_to_git(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "d.csv").write_text(CSV)
            for command in (["init", "-q"], ["add", "."], ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "one"]):
                subprocess.run(["git", "-C", tmp, *command], check=True, capture_output=True)
            self.assertEqual(source.csv_table(root, "d.csv", 1, 1, None, "HEAD")[1][0][0], "4")
            for ref in ("--output=made.txt", "-p", "a b", "HEAD..x"):
                with self.assertRaises(ValueError) as caught:
                    source.csv_table(root, "d.csv", 1, 1, None, ref)
                self.assertIn("is not a git ref", str(caught.exception))
            self.assertEqual(sorted(p.name for p in root.iterdir() if p.name != ".git"), ["d.csv"])

    def test_a_table_that_cannot_be_read_says_so(self):
        refused(self, {"type": "chart", "heading": "h", "file": "d.csv", "rows": [1, 1], "x": "n", "y": "v", "beats": [{"say": "one"}]},
                "could not be read as a table", {"d.csv": 'n,v\na,"' + "x" * 140000 + '"\n'})


class OnlyWhatIsThere(unittest.TestCase):
    """A beat points at what is on screen, counts go up, and what is typed has to mean something."""

    def diagram(self, **fields):
        return {"type": "diagram", "heading": "h", "nodes": [{"label": n} for n in "abcd"],
                "edges": [{"from": "a", "to": "b"}, {"from": "b", "to": "c"}, {"from": "c", "to": "d"}], "beats": [{"say": "one"}], **fields}

    def chart(self, **fields):
        return {"type": "chart", "heading": "h", "file": "d.csv", "rows": [1, 3], "x": "size", "y": "rate",
                "beats": [{"say": "one"}], **fields}

    def test_reveal_is_a_count_that_only_goes_up(self):
        for value in (-1, True, "3", 1.9, 5, "all"):
            refused(self, self.diagram(beats=[{"say": "one", "reveal": value}]), '"reveal" is how many of the 4 nodes')
        refused(self, self.diagram(beats=[{"say": "one", "reveal": 3}, {"say": "two", "reveal": 1}]), "cannot hide one again")
        refused(self, self.chart(y=["hits", "rate"][:1], beats=[{"say": "one", "reveal": "1"}]), "of the 1 series", {"d.csv": CSV})

    def test_a_beat_cannot_point_at_what_is_not_there_yet(self):
        refused(self, self.diagram(beats=[{"say": "one", "reveal": 1, "focus": "d"}]), "'d', which is not on screen yet")
        refused(self, self.diagram(beats=[{"say": "one", "reveal": 3, "follow": ["c", "d"]}]), "'d', which is not on screen yet")
        refused(self, self.diagram(beats=[{"say": "one", "follow": {"from": "a", "to": "b"}}]), '"follow" is an edge written')
        data = {"d.csv": "size,a,b\n1,5,6\n2,7,8\n3,9,10\n"}
        refused(self, self.chart(y=["a", "b"], beats=[{"say": "one", "reveal": 1, "highlight": {"row": 1, "series": "b"}}]),
                "before that column is drawn", data)
        refused(self, self.chart(y=["a", "b"], beats=[{"say": "one", "highlight": {"row": 1}}]), "must say which column it means", data)

    def test_a_scene_needs_a_sentence(self):
        for scene in (self.diagram(beats=[]), {"type": "array", "heading": "h", "items": ["a"]},
                      {"type": "sequence", "heading": "h", "actors": ["A", "B"], "messages": [{"from": "A", "to": "B", "label": "x"}], "beats": []}):
            refused(self, scene, "needs at least one beat")
        refused(self, self.chart(beats=[]), "needs at least one beat", {"d.csv": CSV})

    def test_a_ring_ends_when_the_next_sentence_starts(self):
        scene, _ = build(self.diagram(beats=[{"say": "First this one.", "focus": "a", "follow": ["a", "b"]},
                                             {"say": "Then, much later in the sentence, that one.", "at": "that one", "focus": "b"}]))
        second = scene.starts[1]
        rings = [(op["t"], op["nodes"]) for op in scene.payload["ops"] if op["op"] == "focus"]
        self.assertEqual([nodes for _, nodes in rings], [[0], [], [1]])
        self.assertLess(abs(rings[1][0] - second), 0.1)
        self.assertGreater(rings[2][0], second + 0.5)

    def test_a_diagram_too_wide_says_what_takes_the_width(self):
        chain = {"type": "diagram", "heading": "h", "nodes": [{"label": n} for n in "abcdef"],
                 "edges": [{"from": a, "to": z} for a, z in zip("abcde", "bcdef")] + [{"from": "a", "to": z} for z in "cdef"],
                 "beats": [{"say": "one"}]}
        refused(self, chain, "a layer holds at most 1 node; the rest of the width is arrows that pass a layer")
        refused(self, {**chain, "nodes": [{"label": "a"}], "edges": []}, "one thing alone is not a diagram")

    def test_a_row_may_pass_its_capacity_for_a_moment(self):
        scene, _ = build({"type": "array", "heading": "h", "items": ["a", "b"], "capacity": 2, "beats": [
            {"say": "Store, then evict.", "do": {"push": "c"}}, {"say": "Out goes the front.", "do": {"pop": "front"}}]})
        self.assertEqual([len(op["row"]) for op in scene.payload["ops"] if op["op"] == "change"], [3, 2])
        self.assertEqual(scene.payload["most"], 3)

    def test_cells_that_would_look_the_same_are_the_same(self):
        refused(self, {"type": "array", "heading": "h", "items": ["a", "a "], "beats": [{"say": "one", "mark": {"value": "a"}}]}, "2 do")
        refused(self, {"type": "array", "heading": "h", "items": ["a"], "index": "false", "beats": [{"say": "one"}]}, '"index" is true or false')
        refused(self, {"type": "array", "heading": "h", "items": ["a"], "beats": [{"say": "one", "pointers": 0}]}, '"pointers" names up to 3 places')

    def test_a_chart_takes_only_what_it_uses(self):
        files = {"d.csv": CSV}
        refused(self, self.chart(sub="measured on 4,000 machines"), 'it takes no "sub"', files)
        refused(self, self.chart(lines=[1, 3]), 'it takes no "lines"', files)
        refused(self, self.chart(rows=[True, True]), '"rows" is [first, last]', files)
        refused(self, self.chart(rows=[1, 2, 3]), '"rows" is [first, last]', files)
        refused(self, self.chart(file=5), '"file" is the path of a file', files)
        refused(self, self.chart(expect=5), '"expect" is a piece of text', files)
        refused(self, self.chart(y="size"), "'size' is given twice", files)
        refused(self, self.chart(y=["rate", "rate"]), "names the column 'rate' twice", files)
        refused(self, self.chart(beats=[{"say": "one", "highlight": {"row": 1, "x": "8"}}]), "not both", files)
        refused(self, self.chart(y="t", x="n"), "2 columns are called that", {"d.csv": "n,t,t\na,1,2\nb,3,4\nc,5,6\n"})
        refused(self, self.chart(x="n", y="v", rows=[1, 2]), "has 3 cells and the header has 2", {"d.csv": "n,v\na,1\nb,2,9\n"})
        refused(self, self.chart(x="n", y="v", rows=[1, 1]), "holds NUL characters", {"d.csv": "n,v\na,1\x00\n"})

    def test_expect_can_pin_the_first_row(self):
        build(self.chart(expect="4,2565"), {"d.csv": CSV})
        refused(self, self.chart(expect="4,2565"), "neither the header", {"d.csv": CSV.replace("size,hits,rate,note\n", "size,hits,rate,note\n2,1000,5.0%,\n")})

    def test_a_typed_number_the_chart_does_not_draw_is_pointed_out(self):
        _, warnings = build(self.chart(beats=[{"say": "It takes only 3 milliseconds at size 8.", "highlight": {"x": "8"}}]), {"d.csv": CSV})
        self.assertEqual(len([w for w in warnings if "says 3, which is not a number this chart draws" in w]), 1, warnings)
        _, warnings = build(self.chart(beats=[{"say": "At size {x} it is {value}, up from 12.8.", "highlight": {"x": "8"}}]), {"d.csv": CSV})
        self.assertEqual([w for w in warnings if "not a number this chart draws" in w], [])

    def test_a_first_row_of_numbers_is_probably_not_a_header(self):
        scene = {"type": "chart", "heading": "h", "file": "d.csv", "rows": [1, 2], "x": 1, "y": 2, "beats": [{"say": "one"}]}
        _, warnings = build(scene, {"d.csv": "4,0.50\n8,0.62\n16,0.75\n"})
        self.assertTrue(any("looks like data, not column names" in w for w in warnings), warnings)


class LaidOut(unittest.TestCase):
    """What only the browser can measure: an arrow behind a box, a label with no room, a label that would be cut."""

    @classmethod
    def setUpClass(cls):
        try:
            from idr.render import Studio
            cls.studio = Studio("wide").__enter__()
        except Exception as problem:                       # no browser on this machine
            raise unittest.SkipTest(f"no browser to lay scenes out in ({type(problem).__name__})")

    @classmethod
    def tearDownClass(cls):
        cls.studio.__exit__(None, None, None)

    def problems(self, scene):
        built, _ = build(scene)
        self.studio.problems.clear()
        self.studio._load(built)
        return list(self.studio.problems)

    def chain(self, labels, **fields):
        names = ["Tokenizer", "Parser", "TypeChecker", "Optimizer", "CodeGenerator", "Linker"][:len(labels) + 1]
        return {"type": "diagram", "heading": "h", "nodes": [{"label": n} for n in names],
                "edges": [{"from": a, "to": z, "label": text} for a, z, text in zip(names, names[1:], labels)],
                "beats": [{"say": "one"}], **fields}

    def test_a_label_that_would_hide_its_arrow_is_reported(self):
        found = self.problems(self.chain(["token stream", "syntax tree", "typed tree", "optimised IR", "object files"]))
        self.assertTrue(any("has no clear place" in text and not text.startswith("~") for text in found), found)
        self.assertEqual(self.problems(self.chain(["tokens", "tree", "typed"])), [])

    def test_there_and_back_between_two_boxes_have_a_label_each(self):
        states = {"type": "diagram", "heading": "h", "nodes": [{"label": n} for n in ("idle", "busy", "done", "failed")],
                  "edges": [{"from": "idle", "to": "busy", "label": "start"}, {"from": "busy", "to": "done", "label": "ok"},
                            {"from": "busy", "to": "failed", "label": "error"}, {"from": "failed", "to": "busy", "label": "retry"},
                            {"from": "busy", "to": "busy", "label": "tick"}],
                  "beats": [{"say": "one"}]}
        self.assertEqual(self.problems(states), [])
        self.assertEqual(self.problems({**states, "direction": "down"}), [])

    def test_an_arrow_that_skips_a_layer_goes_round_the_boxes(self):
        fan = {"type": "diagram", "heading": "h", "nodes": [{"label": n} for n in ("router", "auth", "cache", "db", "reply", "config")],
               "edges": [{"from": "router", "to": n} for n in ("auth", "cache", "db", "reply")] + [{"from": "auth", "to": "reply"}],
               "beats": [{"say": "one"}]}
        self.assertEqual(self.problems(fan), [])

    def test_a_cell_text_wider_than_its_cell_is_reported(self):
        row = {"type": "array", "heading": "h", "items": [f"entry_number{i:02d}" for i in range(12)], "beats": [{"say": "one"}]}
        found = self.problems(row)
        self.assertTrue(any("does not fit in a cell when the row has room for 12" in text for text in found), found)
        self.assertEqual(self.problems({**row, "items": ["entry_number00", "b", "c"]}), [])

    def test_numbers_of_points_close_together_do_not_cover_each_other(self):
        text = "t,a,b,c\n" + "".join(f"{i},{100 + i},{100.5 + i},{101 + i}\n" for i in range(1, 9))
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "d.csv").write_text(text)
            scene = {"type": "chart", "heading": "h", "file": "d.csv", "rows": [1, 8], "x": "t", "y": ["a", "b", "c"], "kind": "line",
                     "beats": [{"say": "one", "highlight": [{"row": 4, "series": n} for n in "abc"]}]}
            built, _ = plan.build({"title": "t", "chapters": [{"title": "c", "scenes": [scene]}]}, Path(tmp), "light",
                                  plan.DryNarrator("no such voice"))
        self.studio.problems.clear()
        self.studio._load(built[-1])
        self.assertEqual(self.studio.problems, [])
        boxes = self.studio.page.evaluate("() => [...document.querySelectorAll('.value.pin')].map(e => { const r = e.getBoundingClientRect(); return [r.left, r.top, r.right, r.bottom]; })")
        self.assertEqual(len(boxes), 3)
        for i, p in enumerate(boxes):
            for q in boxes[i + 1:]:
                self.assertFalse(p[0] < q[2] and p[2] > q[0] and p[1] < q[3] and p[3] > q[1], (p, q))

    def test_a_message_that_would_be_cut_is_reported(self):
        def talk(label, a="Client", z="Worker"):
            return {"type": "sequence", "heading": "h", "actors": ["Client", "Gateway", "Auth", "Cache", "Worker"],
                    "messages": [{"from": a, "to": z, "label": label}], "beats": [{"say": "one"}]}
        self.assertEqual(self.problems(talk("do not cache errors", "Worker", "Worker")), [])      # it loops left, where there is room
        self.assertEqual(self.problems(talk("a label of twenty-six chars", "Client", "Worker")), [])
        found = self.problems(talk("this label is far too long to sit between two neighbouring parties in two lines", "Client", "Gateway"))
        self.assertTrue(any("would be cut off" in text for text in found), found)


if __name__ == "__main__":
    unittest.main()
