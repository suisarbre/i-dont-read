"""Tests for what a graph can show beyond a curve: secants, Riemann sums, found points, areas between curves,
curves that change, polar curves and asymptotes; numbers quoted in the narration; and a paper's own commands.

Run from the repository root:  python -m unittest discover tests
"""
import math
import tempfile
import unittest
from pathlib import Path

from idr import plan, plot, texmath


def build(scene, files=None, **top):
    with tempfile.TemporaryDirectory() as tmp:
        for name, text in (files or {}).items():
            (Path(tmp) / name).write_text(text, encoding="utf-8")
        board = {"title": "t", "chapters": [{"title": "c", "scenes": [scene]}], **top}
        if not files:
            board.setdefault("source", "none")
        built, warnings = plan.build(board, Path(tmp), "light", plan.DryNarrator())
        return built[-1].payload, warnings


def graph(**fields):
    return {"type": "plot", "heading": "h", "x": [-3, 3], "beats": [{"say": "one"}], **fields}


def beat(say="one", **actions):
    return [{"say": say, **actions}]


class Secants(unittest.TestCase):
    def test_a_secant_is_the_line_through_two_points(self):
        (mark,) = build(graph(expr="x^2", beats=beat(secant={"x": 1, "other": 3})))[0]["marks"]
        self.assertEqual((mark["kind"], mark["x"], mark["y"], mark["other"]), ("tangent", 1.0, 1.0, [3.0, 9.0]))
        self.assertEqual(mark["dy"] / mark["dx"], 4.0)
        self.assertEqual(mark["tex"], r"\text{slope} = 4")

    def test_a_secant_closes_in_on_the_tangent(self):
        payload, _ = build(graph(expr="x^2", beats=beat(secant={"x": 1, "other": 3, "approach": True})))
        (mark,) = payload["marks"]
        steps = mark["steps"]
        self.assertEqual((mark["kind"], mark["anchor"], len(steps)), ("move", [1.0, 1.0], plan.MOVE_STEPS + 1))
        self.assertEqual(steps[0][4:], ["(3.00, 9.00)", "slope 4.00"])
        for x, y, dx, dy, _, _ in steps[:60]:               # every line on the way goes through both points
            self.assertAlmostEqual(dy / dx, (y - 1) / (x - 1), places=5)
            self.assertAlmostEqual(dy / dx, x + 1, places=6)            # for x squared that slope is x + 1
        self.assertEqual(steps[-1][4:], ["(1.00, 1.00)", "slope 2.00"])       # and the last one is the tangent
        self.assertTrue(any(op["op"] == "travel" for op in payload["ops"]))

    def test_refusals(self):
        for item, why in [({"x": 1, "other": 1}, "two different points"), ({"x": 1}, '"other"'),
                          ({"x": 0, "other": 2, "approach": True}, "corner")]:
            with self.assertRaisesRegex(plan.StoryboardError, why):
                build(graph(expr="abs(x)", beats=beat(secant=item)))


class Sums(unittest.TestCase):
    def total(self, **item):
        (mark,) = build(graph(expr="x^2", x=[0, 2.2], y=[0, 5], beats=beat(riemann={"from": 0, "to": 2, **item})))[0]["marks"]
        return mark

    def test_riemann_sums(self):
        self.assertEqual(self.total(n=4)["tex"], r"n = 4:\ \text{sum} = 1.75")                   # left ends
        self.assertEqual(self.total(n=4, rule="right")["tex"], r"n = 4:\ \text{sum} = 3.75")
        self.assertEqual(self.total(n=4, rule="mid")["tex"], r"n = 4:\ \text{sum} = 2.625")
        rects = self.total(n=4)["rects"]
        self.assertEqual([r[:2] for r in rects], [[0.0, 0.5], [0.5, 1.0], [1.0, 1.5], [1.5, 2.0]])
        self.assertEqual([r[2] for r in rects], [0.0, 0.25, 1.0, 2.25])

    def test_more_rectangles_close_in_on_the_area(self):
        sums = [float(self.total(n=n)["tex"].split()[-1]) for n in (8, 64, 200)]
        self.assertTrue(sums[0] < sums[1] < sums[2] < 8 / 3)
        with self.assertRaisesRegex(plan.StoryboardError, "whole number from 1 to 200"):
            self.total(n=500)

    def test_a_sum_and_an_area_replace_each_other(self):
        payload, _ = build(graph(expr="x^2", x=[0, 2.2], y=[0, 5], beats=[
            {"say": "a", "riemann": {"from": 0, "to": 2, "n": 4}}, {"say": "b", "shade": {"from": 0, "to": 2}}]))
        self.assertEqual([(op["op"], op["mark"]) for op in payload["ops"] if op["op"] in ("show", "hide")],
                         [("show", 0), ("hide", 0), ("show", 1)])


class Found(unittest.TestCase):
    def point(self, **item):
        return build(graph(curves=["x^3 - 3*x", "x"], x=[-2.5, 2.5], y=[-4, 4], beats=beat(point=item)))[0]["marks"][0]["tex"]

    def test_the_engine_finds_the_place(self):
        self.assertEqual(self.point(max=[-2, 0]), r"\left(-1,\ 2\right)")
        self.assertEqual(self.point(min=[0, 2]), r"\left(1,\ -2\right)")
        self.assertEqual(self.point(root=[1, 2.5]), r"\left(1.732,\ 0\right)")
        self.assertEqual(self.point(meet=2, near=[1, 2.5]), r"\left(2,\ 2\right)")

    def test_it_must_be_one_place(self):
        for item, why in [({"root": [-2.5, 2.5]}, "crosses zero 3 times"), ({"root": [0.5, 1.5]}, "does not cross zero"),
                          ({"meet": 2}, "near"), ({"meet": 1, "near": [1, 2]}, "other curve"), ({"root": [1, 9]}, "inside the graph")]:
            with self.assertRaisesRegex(plan.StoryboardError, why, msg=str(item)):
                self.point(**item)
        with self.assertRaisesRegex(ValueError, "jumps across zero"):
            plot.root(plot.Formula("1/x"), -1, 2)

    def test_area_between_two_curves(self):
        payload, _ = build(graph(curves=["x^3 - 3*x", "x"], x=[-2.5, 2.5], y=[-4, 4],
                                 beats=beat(shade={"from": 0, "to": 2, "between": [1, 2]})))
        (mark,) = payload["marks"]
        self.assertEqual(mark["tex"], r"\text{area} = 4")
        self.assertEqual((mark["outline"][-1], mark["base"][-1]), ([2.0, 2.0], [2.0, 2.0]))    # the two edges meet


class Quoted(unittest.TestCase):
    def say(self, text, **actions):
        payload, _ = build(graph(curves=["x^2", "2*x"], y=[-1, 9.5], beats=[{"say": text, **actions}]))
        return " ".join(c["text"].strip() for c in payload["captions"]).strip()

    def test_the_narration_quotes_what_the_engine_worked_out(self):
        self.assertEqual(self.say("The slope there is {slope}.", tangent={"x": 1.5}), "The slope there is 3.")
        self.assertEqual(self.say("It sits at {x}, {y:2}.", point={"x": "sqrt(2)"}), "It sits at 1.414, 2.")
        self.assertEqual(self.say("Area {area:3}.", shade={"from": 0, "to": 2}), "Area 2.67.")
        self.assertEqual(self.say("First {a.y}, then {b.y}.", point=[{"x": 1, "as": "a"}, {"x": 2, "on": 2, "as": "b"}]),
                         "First 1, then 4.")
        self.assertEqual(self.say("Slope {slope}.", point={"x": -2}, tangent={"x": -2}), "Slope −4.")

    def test_a_quote_must_name_one_number(self):
        for text, actions, why in [("It is {y}.", {}, "no mark is made"), ("It is {slope}.", {"point": {"x": 1}}, "give x, y"),
                                   ("It is {y}.", {"point": [{"x": 1}, {"x": 2}]}, "several marks"),
                                   ("It is {p.y}.", {"point": {"x": 1}}, 'no mark is named "p"'),
                                   ("It is {p.area}.", {"point": {"x": 1, "as": "p"}}, "has no area")]:
            with self.assertRaisesRegex(plan.StoryboardError, why, msg=text):
                self.say(text, **actions)


class Changing(unittest.TestCase):
    def test_a_curve_moves_through_its_stages(self):
        payload, warnings = build(graph(curves=["sin(x)", {"stages": ["x", "x - x^3/6", "x - x^3/6 + x^5/120"]}], y=[-2, 2], beats=[
            {"say": "a", "reveal": 2}, {"say": "b", "stage": 2}, {"say": "c", "stage": 3}]))
        curve = payload["curves"][1]
        self.assertEqual((curve["draw"], len(curve["frames"]), len(curve["xs"])), ("stages", 3, plot.SAMPLES))
        self.assertEqual(curve["labels"][1], r"y = x - \frac{x^{3}}{6}")
        k = curve["xs"].index(min(curve["xs"], key=lambda v: abs(v - 1.5)))
        x = curve["xs"][k]
        self.assertAlmostEqual(curve["frames"][1][k], x - x ** 3 / 6, places=6)           # each stage is a real graph
        self.assertEqual([(op["curve"], op["to"]) for op in payload["ops"] if op["op"] == "stage"], [(1, 1), (1, 2)])
        self.assertFalse(warnings)

    def test_a_number_in_the_formula_sweeps(self):
        payload, _ = build(graph(curves=[{"expr": "sin(k*x)", "vary": {"k": [1, 4]}}], y=[-1.5, 1.5],
                                 beats=beat(sweep={"seconds": 3})))
        curve = payload["curves"][0]
        self.assertEqual((len(curve["frames"]), curve["texts"][0], curve["texts"][-1]), (49, "k = 1.00", "k = 4.00"))
        (op,) = [op for op in payload["ops"] if op["op"] == "stage"]
        self.assertEqual((op["to"], op["dur"], op["steady"]), (48, 3.0, True))

    def test_refusals_and_a_warning(self):
        stages = {"stages": ["x", "x^2"]}
        for fields, why in [({"curves": [{"stages": ["x"]}]}, "2 to 8 formulas"),
                            ({"curves": [{"stages": ["x", "1/x"]}]}, "no value somewhere"),
                            ({"curves": [stages], "beats": beat(point={"x": 1})}, "curve that changes"),
                            ({"curves": [stages], "beats": beat(stage=3)}, "from 1 to 2"),
                            ({"curves": [stages], "beats": beat(sweep=True)}, '"vary"'),
                            ({"expr": "x", "beats": beat(stage=2)}, "has none"),
                            ({"curves": [{"expr": "sin(k*x)", "vary": {"x": [1, 2]}}]}, "one letter")]:
            with self.assertRaisesRegex(plan.StoryboardError, why, msg=str(fields)):
                build(graph(y=[-3, 3], **fields))
        _, warnings = build(graph(curves=[stages], y=[-3, 3]))
        self.assertTrue(any("never does" in w for w in warnings))


class PolarAndAsymptotes(unittest.TestCase):
    def test_a_polar_curve(self):
        payload, _ = build(graph(curves=[{"r": "1 + cos(theta)", "theta": [0, "2*pi"]}], y=[-2, 2],
                                 beats=beat(point={"t": "pi/2"}, tangent={"t": "pi/2"})))
        self.assertEqual(payload["curves"][0]["tex"], r"r = 1 + \cos\left(\theta\right)")
        point, tangent = payload["marks"]
        self.assertEqual(point["tex"], r"\left(0,\ 1\right)")
        self.assertEqual(tangent["tex"], r"\text{slope} = 1")
        for x, y in payload["curves"][0]["lines"][0][::40]:
            theta = math.atan2(y, x)
            self.assertAlmostEqual(math.hypot(x, y), 1 + math.cos(theta), places=4)

    def test_an_asymptote_is_checked(self):
        guides = build(graph(expr="1/(x - 1)", x=[-4, 6], y=[-6, 6], asymptotes=[{"x": 1}, {"y": 0}]))[0]["guides"]
        self.assertEqual(guides, [{"x": 1.0, "label": "x = 1"}, {"y": 0.0, "label": "y = 0"}])
        for claim, why in [({"x": 2}, "not a vertical asymptote"), ({"y": 1}, "horizontal asymptote"), ({"x": 9}, "outside")]:
            with self.assertRaisesRegex(plan.StoryboardError, why):
                build(graph(expr="1/(x - 1)", x=[-4, 6], y=[-6, 6], asymptotes=[claim]))


class Macros(unittest.TestCase):
    PAPER = "\n".join([r"\documentclass{article}", r"\usepackage{mine}", r"\newcommand{\norm}[1]{\left\lVert #1 \right\rVert}",
                       r"\DeclareMathOperator*{\argmin}{arg\,min}", r"% \newcommand{\gone}{x}", r"\def\half{\frac12}",
                       r"\begin{document}", r"\begin{equation}", r"  \vv = \half \argmin_x \norm{x}", r"\end{equation}",
                       r"\end{document}"])

    def test_a_papers_own_commands_are_read(self):
        found = texmath.macros(self.PAPER)
        self.assertEqual(found, {r"\norm": r"\left\lVert #1 \right\rVert", r"\argmin": r"\operatorname*{arg\,min}", r"\half": r"\frac12"})
        self.assertEqual(texmath.macros(r"\newcommand{\E}[2][p]{x} \newcommand{\bad}{\href{a}{b}}"), {})

    def test_its_formulas_parse_with_them(self):
        scene = {"type": "math", "heading": "h", "file": "paper.tex", "lines": [8, 10], "beats": [{"say": "one"}]}
        payload, _ = build(scene, files={"paper.tex": self.PAPER, "mine.sty": r"\newcommand{\vv}{\mathbf{v}}"})
        self.assertEqual(payload["macros"][r"\vv"], r"\mathbf{v}")                        # from the file it pulls in
        self.assertIn(r"\vv = \half \argmin_x \norm{x}", payload["blocks"][0])            # shown as the author wrote it
        with self.assertRaisesRegex(plan.StoryboardError, r"Undefined control sequence: \\vv"):
            build(scene, files={"paper.tex": self.PAPER})


class Checks(unittest.TestCase):
    def test_a_word_written_as_math_is_warned_about(self):
        scene = lambda tex: {"type": "math", "heading": "h", "tex": [tex], "beats": [{"say": "one"}]}
        self.assertTrue(any("'energy'" in w for w in build(scene("energy = mass"))[1]))
        for fine in (r"\text{energy} = m c^2", r"\begin{pmatrix} a & b \end{pmatrix}", r"\operatorname{argmax}_x f(x)"):
            self.assertFalse(build(scene(fine))[1], msg=fine)

    def test_axis_names_are_short(self):
        with self.assertRaisesRegex(plan.StoryboardError, "short name for the axis"):
            build(graph(expr="x", xlabel="time since the start of the experiment"))
