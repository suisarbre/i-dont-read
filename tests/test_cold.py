"""Tests for what two agents ran into when they made videos from SKILL.md alone: a paper's equation numbers,
its commands with optional arguments and its LaTeX tables; a capital A read as the article; a caption rounded
differently from its label; marks drawn before their curve; and what a check and a preview can tell you.

Run from the repository root:  python -m unittest discover tests
"""
import contextlib
import io
import tempfile
import types
import unittest
from pathlib import Path

from idr import cli, plan, source, speech, texmath

STY = r"""
\newcommand{\x}{\mathbf{x}}
\newcommand{\norm}[1]{\left\lVert #1 \right\rVert}
\newcommand{\half}[1][1]{\frac{#1}{2}}
\newcommand{\pair}[2][0]{(#1, #2)}
\newcommand{\hL}{\half[L]}
"""
PAPER = r"""\documentclass{article}
\usepackage{notation}
\begin{document}
\begin{equation}\label{a}
  a = \x
\end{equation}
\begin{align}
  b &= 1 \\
  c &= 2 \nonumber \\
  d &= 3
\end{align}
\begin{equation*}
  e = 0
\end{equation*}
\begin{equation}
  f = \half[L] \norm{\x} + \half + \hL
\end{equation}
\begin{tabular}{l|rr}
\toprule
Step $\eta$ & Factor & \textbf{Result} \\
\midrule
0.1 & $-0.8$ & 50\% \\
0.6 & 1.4 & diverges \\ \bottomrule
\end{tabular}
\end{document}
"""


def build(scene, files=None, narrator=None, **top):
    with tempfile.TemporaryDirectory() as tmp:
        for name, text in (files or {}).items():
            (Path(tmp) / name).write_text(text, encoding="utf-8")
        board = {"title": "t", "chapters": [{"title": "c", "scenes": [scene]}], **top}
        if not files:
            board.setdefault("source", "none")
        built, warnings = plan.build(board, Path(tmp), "light", narrator or plan.DryNarrator("no such voice"))
        return built[-1], warnings


def paper(lines, text=PAPER, **fields):
    scene = {"type": "math", "heading": "h", "file": "p.tex", "lines": lines, "beats": [{"say": "one"}], **fields}
    return build(scene, {"p.tex": text, "notation.sty": STY})


def graph(**fields):
    return {"type": "plot", "heading": "h", "x": [-3, 3], "beats": [{"say": "one"}], **fields}


class EquationNumbers(unittest.TestCase):
    def test_an_equation_keeps_the_number_the_paper_gives_it(self):
        scene, warnings = paper([15, 17])
        self.assertIn(r"\tag{4}", scene.payload["blocks"][0])            # 1, then 2 and 3 in the align, then this one
        self.assertIn(r"\begin{equation*}", scene.payload["blocks"][0])   # so KaTeX does not count from 1 again
        self.assertEqual(warnings, [])

    def test_rows_are_numbered_as_latex_numbers_them(self):
        block = paper([7, 11])[0].payload["blocks"][0]
        self.assertEqual([block.count(rf"\tag{{{n}}}") for n in (1, 2, 3, 4)], [0, 1, 1, 0])
        self.assertLess(block.index(r"\tag{2}"), block.index(r"\nonumber"))
        self.assertNotIn(r"\tag", paper([12, 14])[0].payload["blocks"][0])   # equation*: the paper prints no number

    def test_a_number_that_cannot_be_told_is_not_shown(self):
        for change in [lambda t: t.replace(r"\begin{document}", "\\numberwithin{equation}{section}\n\\begin{document}", 1),
                       lambda t: t.replace(r"\documentclass{article}", r"\documentclass{book}"),
                       lambda t: t.replace("\\begin{document}\n", "\\begin{document}\\input{intro}", 1),
                       lambda t: t.replace("\\begin{document}\n", "", 1)]:
            text = change(PAPER)
            first = text.split("\n").index(r"  f = \half[L] \norm{\x} + \half + \hL")
            scene, warnings = paper([first, first + 2], text)
            self.assertNotIn(r"\tag", scene.payload["blocks"][0])
            self.assertIn(r"\begin{equation*}", scene.payload["blocks"][0])
            self.assertTrue(any("without its equation number" in w for w in warnings), warnings)

    def test_counting(self):
        text = "\\begin{document}\n\\begin{gather} a \\\\ b \\end{gather}\n\\begin{equation} c \\tag{A} \\end{equation}\n"
        at = len(text)
        text += "\\begin{align} d &= \\begin{cases} 1 \\\\ 2 \\end{cases} \\\\ e \\notag \\end{align}"
        self.assertEqual(texmath.equation_numbers(text, at), [3, None])
        self.assertIs(texmath.equation_numbers("\\begin{document}\n$$x$$", 17), False)
        self.assertIsNone(texmath.equation_numbers("\\begin{document}\\begin{align} a \\\\ \\end{align}", 16))
        self.assertIsNone(texmath.equation_numbers(text, at, {"\\be": "\\begin{equation}"}))


class OptionalArguments(unittest.TestCase):
    def test_they_are_written_out_the_way_latex_would(self):
        optional = texmath.macros(STY).optional
        self.assertEqual(optional["\\half"], (1, "1", "\\frac{#1}{2}"))
        self.assertEqual(texmath.expand(r"\half[L] + \half x", optional), r"{\frac{L}{2}} + {\frac{1}{2}} x")
        self.assertEqual(texmath.expand(r"\pair[a]{b}\pair c", optional), r"{(a, b)}{(0, c)}")
        self.assertEqual(texmath.expand(r"\half[\frac{a}{b}]", optional), r"{\frac{\frac{a}{b}}{2}}")
        self.assertEqual(texmath.expand(r"\halfway", optional), r"\halfway")

    def test_a_formula_that_uses_one_is_read_from_the_paper(self):
        scene, _ = paper([15, 17], beats=[{"say": "one", "mark": {"line": 1, "tex": r"\half[L]"}}])
        block = scene.payload["blocks"][0]
        self.assertIn(r"\htmlClass{idr-m0}{{\frac{L}{2}}}", block)
        self.assertNotIn(r"\half", block)
        self.assertEqual(scene.payload["macros"]["\\hL"], r"{\frac{L}{2}}")   # a plain command written with one


class LatexTables(unittest.TestCase):
    def table(self, text=PAPER, lines=(18, 24)):
        scene = {"type": "table", "heading": "h", "file": "p.tex", "lines": list(lines), "beats": [{"say": "one"}]}
        return build(scene, {"p.tex": text, "notation.sty": STY})[0].payload

    def test_a_tabular_is_read_as_the_paper_has_it(self):
        payload = self.table()
        self.assertEqual(payload["header"][0][0], {"text": "Step "})
        self.assertEqual(payload["header"][0][1]["tex"], r"\eta")
        self.assertEqual(payload["header"][1:], ["Factor", "Result"])
        self.assertEqual(payload["rows"], [["0.1", "−0.8", "50%"], ["0.6", "1.4", "diverges"]])
        self.assertEqual(payload["aligns"], [None, "right", "right"])
        self.assertEqual(payload["sub"], "p.tex  ·  lines 18–24")

    def test_what_it_cannot_show_is_refused_by_name(self):
        for change, why in [(lambda t: t.replace("0.6 & 1.4", r"\multicolumn{2}{c}{both}"), "span columns"),
                            (lambda t: t.replace("diverges", r"\cite{x}"), r"uses \cite"),
                            (lambda t: t.replace("0.6 & 1.4 &", "0.6 &"), "2 cells")]:
            with self.assertRaises(ValueError) as caught:
                self.table(change(PAPER))
            self.assertIn(why, str(caught.exception))
        with self.assertRaises(ValueError) as caught:
            self.table(lines=(4, 6))
        self.assertIn("no LaTeX table", str(caught.exception))


class TheLetterA(unittest.TestCase):
    def test_a_name_is_read_as_the_letter(self):
        for written, said in [("call it A of x.", "call it eigh of x."), ("A'(x) equals f(x).", "eigh prime of x equals f of x."),
                              ("The area A(x) grows.", "The area eigh of x grows."), ("the matrix A times x", "the matrix eigh times x"),
                              ("A plus B is C.", "eigh plus B is C.")]:
            self.assertEqual(speech.spoken(written), said)

    def test_the_article_stays_the_article(self):
        for sentence in ["A function has a slope.", "A prime example of this.", "It is a line. A point moves along it.",
                         "A plus sign means add.", "A of the three options works."]:
            self.assertEqual(speech.spoken(sentence), sentence)


class Digits(unittest.TestCase):
    def test_the_label_and_the_caption_round_together(self):
        scene, _ = build(graph(expr="x^2", y=[-1, 9.5], beats=[{"say": "About {area}.", "shade": {"from": 0, "to": 2, "digits": 2}}]))
        self.assertEqual(scene.payload["marks"][0]["tex"], r"\text{area} \approx 2.7")
        self.assertEqual(scene.payload["captions"][0]["text"], "About 2.7.")

    def test_a_caption_may_not_round_on_its_own(self):
        with self.assertRaises(plan.StoryboardError) as caught:
            build(graph(expr="x^2", y=[-1, 9.5], beats=[{"say": "About {area:2}.", "shade": {"from": 0, "to": 2}}]))
        self.assertIn('put "digits": 2 on the mark', str(caught.exception))
        with self.assertRaises(plan.StoryboardError):
            build(graph(expr="x^2", beats=[{"say": "one", "point": {"x": 1, "digits": 0}}]))


class Order(unittest.TestCase):
    def test_a_mark_waits_for_its_curve_to_be_drawn(self):
        scene, _ = build(graph(expr="x^2", y=[-1, 9.5], beats=[{"say": "one", "reveal": 1, "shade": {"from": 0, "to": 2}}]))
        ops = scene.payload["ops"]
        reveal = next(op["t"] for op in ops if op["op"] == "reveal")
        self.assertGreaterEqual(next(op["t"] for op in ops if op["op"] == "show"), reveal + plan.DRAW)


class Lengths(unittest.TestCase):
    def test_numbers_take_as_long_as_they_take_to_say(self):
        dry = plan.DryNarrator("no such voice")
        words, numbers = "Eight rectangles give a little more, sixteen give a bit less.", \
                         "Eight rectangles give 6.143, sixteen give 6.092, more 6.048."
        self.assertGreaterEqual(len(words), len(numbers))            # no longer on the page, much longer aloud
        self.assertGreater(dry.estimate(numbers), 1.5 * dry.estimate(words))
        dry.say(words)
        self.assertEqual(dry.guessed, 1)

    def test_a_sentence_spoken_before_keeps_its_real_length(self):
        from idr import tts
        real = tts.remembered
        tts.remembered = lambda text, voice, speed: (3.21, [(0.0, 3.2, 9)])
        try:
            dry = plan.DryNarrator()
            clip = dry.say("Anything at all.")
        finally:
            tts.remembered = real
        self.assertEqual((clip.duration, clip.words, dry.guessed), (3.21, [(0.0, 3.2, 9)], 0))


class Looking(unittest.TestCase):
    def test_a_frame_carries_the_caption_of_the_sentence_that_made_it(self):
        scene, _ = build(graph(expr="x^2", y=[-1, 9.5], beats=[
            {"say": "Here is the curve, drawn from left to right.", "point": {"x": 1}},
            {"say": "Now wait for it, and only then mark the slope there.", "at": "mark the slope", "tangent": {"x": 1}}]))
        (first, _), *_ = cli._moments(scene, True)
        self.assertLess(first, scene.starts[1])                # before the second sentence begins, not inside it

    def test_something_that_takes_time_is_shown_half_way(self):
        scene, _ = build(graph(expr="x^2", y=[-1, 9.5], beats=[{"say": "A point travels along the whole curve.",
                                                               "move": {"from": -2, "to": 2}}]))
        travel = next(op for op in scene.payload["ops"] if op["op"] == "travel")
        self.assertIn((travel["t"] + travel["dur"] / 2, "  ·  half-way"), cli._moments(scene, True))
        self.assertEqual(len(cli._moments(scene, False)), 1)

    def test_the_listing_prints_a_heading_as_it_was_written(self):
        scene, _ = build(graph(expr="x^2", heading="Why $x^2$ grows"))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cli._report([scene], [], 2)
        self.assertIn("Why $x^2$ grows", out.getvalue())
        self.assertIn("2 sentence(s) not spoken yet", out.getvalue())


if __name__ == "__main__":
    unittest.main()
