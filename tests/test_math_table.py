"""Tests for math and table scenes and inline $...$ (see docs/spec-math-table.md).

Run from the repository root:  python -m unittest discover tests
The KaTeX checks start the same headless browser the renderer uses.
"""
import tempfile
import unittest
from pathlib import Path

from idr import plan, source, texmath


def build(scenes, files=None, **top):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for name, text in (files or {}).items():
            (root / name).write_text(text, encoding="utf-8")
        board = {"title": "t", "chapters": [{"title": "c", "scenes": scenes}], **top}
        if not any(plan._shows_source(scene) for scene in scenes):
            board.setdefault("source", "none")              # nothing read from a file: the video has to say so
        return plan.build(board, root, "light", plan.DryNarrator())


def payload(scenes, files=None, **top):
    built, warnings = build(scenes, files, **top)
    return built[-1].payload, warnings


class Spans(unittest.TestCase):
    def found(self, text):
        return [(text[s:e], display) for s, e, _, display in texmath.spans(text)]

    def test_inline_and_display(self):
        self.assertEqual(self.found("cost $\\log_2 1/p$ bits"), [("$\\log_2 1/p$", False)])
        self.assertEqual(self.found("so $$ H = \\sum p $$ here"), [("$$ H = \\sum p $$", True)])
        self.assertEqual(self.found("$a$ and $b$"), [("$a$", False), ("$b$", False)])
        self.assertEqual(self.found("$\\frac{1}{2}$"), [("$\\frac{1}{2}$", False)])

    def test_dollars_that_are_not_math(self):
        self.assertEqual(self.found("costs $5 to $10 today"), [])
        self.assertEqual(self.found("echo $HOME and $PATH"), [])
        self.assertEqual(self.found("a \\$5 note"), [])
        self.assertEqual(self.found("$ x$"), [])                 # opening $ followed by a space
        self.assertEqual(self.found("$x $"), [])                 # closing $ after a space

    def test_price_before_math(self):
        self.assertEqual(self.found("pay $5 and $x$"), [("$x$", False)])

    def test_unescape_and_balanced(self):
        self.assertEqual(texmath.unescape("a \\$5"), "a $5")
        self.assertTrue(texmath.balanced("\\frac{1}{p}"))
        self.assertFalse(texmath.balanced("\\frac{1}{p"))
        self.assertFalse(texmath.balanced("x}"))
        self.assertFalse(texmath.balanced("a \\"))


class Clean(unittest.TestCase):
    def test_math_keeps_its_characters(self):
        self.assertEqual(source.clean("*bold* and $x_1 * y_2$ here"), "bold and $x_1 * y_2$ here")
        self.assertEqual(source.clean("`$x_1$` stays"), "$x_1$ stays")


class Tables(unittest.TestCase):
    def test_markdown(self):
        text = "| a | b \\| c | `x|y` |\n|:--|--:|:-:|\n| 1 | 2 | 3 |\n| 4 |\n"
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "t.md").write_text(text)
            header, aligns, rows, first = source.md_table(Path(tmp), "t.md", 1, 4)
        self.assertEqual(header, ["a", "b | c", "x|y"])
        self.assertEqual(aligns, ["left", "right", "center"])
        self.assertEqual(rows, [["1", "2", "3"], ["4", "", ""]])
        self.assertTrue(first.startswith("| a"))

    def test_markdown_needs_a_header(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "t.md").write_text("text\n| 1 | 2 |\n")
            with self.assertRaises(ValueError):
                source.md_table(Path(tmp), "t.md", 1, 2)

    def test_csv(self):
        text = 'name,size,note\n"a, b",10,x\nc,20,y\n'
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "t.csv").write_text(text)
            header, rows = source.csv_table(Path(tmp), "t.csv", 1, 2, ["note", "name"])
            self.assertEqual(header, ["note", "name"])
            self.assertEqual(rows, [["x", "a, b"], ["y", "c"]])
            with self.assertRaises(ValueError):
                source.csv_table(Path(tmp), "t.csv", 1, 2, ["missing"])


class DisplayMath(unittest.TestCase):
    def test_blocks(self):
        text = "x\n\\begin{align}\n a &= b \\label{e1} \\\\\n c &= d\n\\end{align}\n\\[ y \\]\n$$ z $$\n"
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "p.tex").write_text(text)
            blocks, _, _ = source.display_math(Path(tmp), "p.tex", 1, 7)
        self.assertEqual(len(blocks), 3)
        self.assertNotIn("\\label", blocks[0])
        self.assertTrue(blocks[0].startswith("\\begin{align}"))
        self.assertEqual(blocks[1:], ["y", "z"])

    def test_cut_block_and_no_math(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "p.tex").write_text("\\begin{equation}\n a\n\\end{equation}\nplain words\n")
            with self.assertRaises(ValueError):
                source.display_math(Path(tmp), "p.tex", 1, 2)
            with self.assertRaises(ValueError):
                source.display_math(Path(tmp), "p.tex", 4, 4)


class MathScene(unittest.TestCase):
    def test_marks_are_wrapped(self):
        p, _ = payload([{"type": "math", "heading": "h", "tex": ["a + \\frac{1}{p}"],
                         "beats": [{"say": "the fraction", "mark": {"line": 1, "tex": "\\frac{1}{p}"}, "note": "n"}]}])
        self.assertEqual(p["blocks"], ["a + \\htmlClass{idr-m0}{\\frac{1}{p}}"])
        self.assertEqual([op["op"] for op in p["ops"] if op["op"] in ("mark", "note")], ["mark", "note"])

    def test_mark_errors(self):
        for mark in ({"line": 1, "tex": "zzz"}, {"line": 1, "tex": "\\frac{1}{p"}, {"line": 2, "tex": "a"}):
            with self.assertRaises(plan.StoryboardError):
                build([{"type": "math", "tex": ["a + \\frac{1}{p}"], "beats": [{"say": "x", "mark": mark}]}])

    def test_too_many_formulas(self):
        with self.assertRaises(plan.StoryboardError):
            build([{"type": "math", "tex": ["a"] * 5, "beats": [{"say": "x"}]}])

    def test_bad_latex_in_a_formula_is_an_error(self):
        with self.assertRaises(plan.StoryboardError) as caught:
            build([{"type": "math", "tex": ["\\frac{1}"], "beats": [{"say": "x"}]}])
        self.assertIn("LaTeX error", str(caught.exception))


class Inline(unittest.TestCase):
    def test_compare_points_become_segments(self):
        p, _ = payload([{"type": "compare", "heading": "h",
                         "columns": [{"title": "A", "points": ["cost $p$"]}, {"title": "B", "points": ["$5 to $10"]}],
                         "beats": [{"say": "x"}]}])
        self.assertEqual(p["columns"][0]["points"][0], [{"text": "cost "}, {"tex": "p", "display": False, "raw": "$p$"}])
        self.assertEqual(p["columns"][1]["points"][0], "$5 to $10")

    def test_bad_inline_latex_falls_back_to_the_raw_text(self):
        p, warnings = payload([{"type": "compare", "heading": "h",
                                "columns": [{"title": "A", "points": ["see $\\frac{1}$ here"]},
                                            {"title": "B", "points": ["b"]}],
                                "beats": [{"say": "x"}]}])
        self.assertEqual(p["columns"][0]["points"][0][1], {"text": "$\\frac{1}$"})
        self.assertTrue(any("not valid LaTeX" in w for w in warnings))

    def test_math_off(self):
        p, _ = payload([{"type": "compare", "heading": "h", "math": False,
                         "columns": [{"title": "A", "points": ["cost $p$"]}, {"title": "B", "points": ["b"]}],
                         "beats": [{"say": "x"}]}])
        self.assertEqual(p["columns"][0]["points"][0], "cost $p$")

    def test_quote_mark_may_hold_math_but_not_cut_it(self):
        files = {"q.md": "A symbol costs $\\log_2 1/p$ bits.\n"}
        p, _ = payload([{"type": "quote", "file": "q.md", "lines": [1, 1],
                         "beats": [{"say": "x", "mark": "$\\log_2 1/p$ bits"}]}], files)
        parts = p["paragraphs"][0]
        self.assertEqual([part.get("mark") for part in parts], [None, 0, 0, None])
        self.assertEqual(parts[1]["tex"], "\\log_2 1/p")
        with self.assertRaises(plan.StoryboardError):
            build([{"type": "quote", "file": "q.md", "lines": [1, 1],
                    "beats": [{"say": "x", "mark": "1/p$ bits"}]}], files)


class TableScene(unittest.TestCase):
    def table(self, header, rows, beats=None):
        return [{"type": "table", "heading": "h", "header": header, "rows": rows,
                 "beats": beats or [{"say": "x"}]}]

    def test_highlight_and_alignment(self):
        p, _ = payload(self.table(["name", "size"], [["a", "10"], ["b", "2.5%"]],
                                  [{"say": "x", "highlight": {"col": "size"}, "note": "n"},
                                   {"say": "y", "highlight": {"cell": [2, 1]}}, {"say": "z", "highlight": None}]))
        self.assertEqual(p["aligns"], [None, "right"])
        hl = [(op["row"], op["col"], op["on"]) for op in p["ops"] if op["op"] == "hl"]
        self.assertEqual(hl, [(None, 1, True), (1, 0, True), (None, None, False)])

    def test_limits(self):
        with self.assertRaises(plan.StoryboardError):
            build(self.table(["c"] * 7, [["x"] * 7]))
        with self.assertRaises(plan.StoryboardError):
            build(self.table(["c"], [["x"]] * 9))
        with self.assertRaises(plan.StoryboardError):
            build(self.table(["a", "b"], [["x"]]))
        _, warnings = build(self.table(["c"], [["x" * 41]]))
        self.assertTrue(any("over 40" in w for w in warnings))

    def test_unknown_column(self):
        with self.assertRaises(plan.StoryboardError):
            build(self.table(["a"], [["1"]], [{"say": "x", "highlight": {"col": "b"}}]))


if __name__ == "__main__":
    unittest.main()
