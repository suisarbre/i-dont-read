"""Tests for the places where a graph or a formula could be shown wrong without anyone noticing.

Each of these was found by feeding the engine hostile input: it used to pass the check and put something
false on screen (a slope at a corner, an area across a pole, a slow wave that was really a fast one).

Run from the repository root:  python -m unittest discover tests
"""
import math
import tempfile
import unittest
from pathlib import Path

import numpy as np

from idr import plan, plot


def build(scene):
    with tempfile.TemporaryDirectory() as tmp:
        board = {"title": "t", "source": "none", "chapters": [{"title": "c", "scenes": [scene]}]}
        return plan.build(board, Path(tmp), "light", plan.DryNarrator())[0][-1].payload


def graph(**fields):
    return {"type": "plot", "heading": "h", "x": [-3, 3], "beats": [{"say": "one"}], **fields}


def marked(**beat):
    return [{"say": "one", **beat}]


def formulas(tex, **beat):
    return {"type": "math", "heading": "h", "tex": tex if isinstance(tex, list) else [tex], "beats": [{"say": "one", **beat}]}


class Sampling(unittest.TestCase):
    def test_a_wave_too_fast_to_follow_is_not_drawn_as_a_slow_one(self):
        with self.assertRaisesRegex(plan.StoryboardError, "too fast to be drawn"):
            build(graph(expr="sin(5000*x)"))            # 800 samples of it look like 19 gentle waves
        with self.assertRaisesRegex(plan.StoryboardError, "too fast to be drawn"):
            build(graph(curves=[{"x": "sin(5000*t)", "y": "cos(4999*t)", "t": [0, "2*pi"]}], x=[-2, 2]))

    def test_a_fast_curve_gets_more_samples(self):
        points = lambda expr, **f: sum(len(line) for line in build(graph(expr=expr, **f))["curves"][0]["lines"])
        self.assertEqual(points("x^2"), plot.SAMPLES)
        self.assertEqual(points("sin(100*x)"), plot.SAMPLES * 4)
        self.assertEqual(points("sin(1/x)", x=[-0.5, 0.5]), plot.SAMPLES * 16)      # wild only near 0: still drawn

    def test_the_line_through_the_samples_is_the_curve(self):
        f = plot.Formula("sin(100*x)")
        (line,) = plot.strokes(f, -3, 3, -1.2, 1.2)
        xs, ys = np.array(line).T
        mid = (xs[:-1] + xs[1:]) / 2
        self.assertLess(float(np.abs(f(mid) - (ys[:-1] + ys[1:]) / 2).max()), 0.01)

    def test_a_step_is_not_joined_up(self):
        treads = plot.strokes(plot.Formula("floor(x)"), -3, 3, -3.5, 3.5)
        self.assertEqual(len(treads), 7)                    # six treads and the single point at x = 3
        for tread in treads[:6]:
            self.assertEqual(len({y for _, y in tread}), 1)                         # each one is level
            self.assertAlmostEqual(tread[-1][0] - tread[0][0], 1.0, places=6)      # and a whole unit long

    def test_a_small_range_is_not_rounded_flat(self):
        (line,) = build(graph(expr="x", x=[0, 1e-9]))["curves"][0]["lines"]
        self.assertEqual(len({x for x, _ in line}), plot.SAMPLES)
        self.assertAlmostEqual(line[-1][1], 1e-9)

    def test_a_thin_peak_is_shown_whole_and_a_pole_is_cut(self):
        self.assertGreater(build(graph(expr="exp(-(40*x)^2)", x=[-1, 1]))["y"][1], 1.0)
        self.assertLess(build(graph(expr="1/x"))["y"][1], 20)
        self.assertLess(build(graph(expr="tan(x)", x=[-200, 200]))["y"][1], 20)     # 127 poles, one sample right by one

    def test_scattered_points_and_overflow_are_refused(self):
        with self.assertRaisesRegex(plan.StoryboardError, "scattered points"):
            build(graph(expr="(-2)^x"))
        with self.assertRaisesRegex(plan.StoryboardError, "too large to draw"):
            build(graph(expr="x^1000"))


class Tangents(unittest.TestCase):
    def slope(self, beat, **fields):
        return build(graph(beats=marked(tangent=beat), **fields))["marks"][0]["tex"]

    def test_no_tangent_where_there_is_none(self):
        for fields, beat, why in [({"expr": "abs(x)"}, {"x": 0}, "corner"),
                                  ({"expr": "floor(x)"}, {"x": 1}, "jumps"),
                                  ({"expr": "sqrt(x)", "x": [-1, 4]}, {"x": 0}, "no tangent"),
                                  ({"curves": [{"equation": "abs(x) + abs(y) = 1"}], "y": [-2, 2]}, {"x": 1, "y": 0}, "corner"),
                                  ({"curves": [{"equation": "x*y = 0"}], "y": [-2, 2]}, {"x": 0, "y": 0}, "no tangent")]:
            with self.assertRaisesRegex(plan.StoryboardError, why, msg=str(fields)):
                self.slope(beat, **fields)

    def test_vertical_tangents(self):
        cycloid = {"curves": [{"x": "t - sin(t)", "y": "1 - cos(t)", "t": [-1, 7]}], "x": [-2, 8]}
        self.assertEqual(self.slope({"x": 0}, expr="cbrt(x)"), r"\text{vertical}")
        self.assertEqual(self.slope({"t": 0}, **cycloid), r"\text{vertical}")       # a cusp: it used to say slope = 0
        self.assertEqual(self.slope({"x": 2, "y": 0}, curves=[{"equation": "x^2 + y^2 = 4"}], y=[-3, 3]), r"\text{vertical}")

    def test_slopes_are_right_where_the_curve_is_wild_or_flat(self):
        self.assertEqual(self.slope({"x": 0.001}, expr="sin(1/x)"), r"\text{slope} \approx -562379")
        self.assertEqual(self.slope({"x": "pi/2"}, expr="sin(x)", x=["-pi", "pi"]), r"\text{slope} = 0")
        self.assertEqual(self.slope({"x": 0}, expr="x*abs(x)"), r"\text{slope} = 0")
        self.assertEqual(self.slope({"x": 1}, expr="abs(x)"), r"\text{slope} = 1")
        self.assertEqual(self.slope({"t": 0}, curves=[{"x": "t^3", "y": "t^3", "t": [-1, 1]}]), r"\text{slope} = 1")
        self.assertEqual(self.slope({"t": 0}, curves=[{"x": "t", "y": "t^2", "t": [0, 2]}]), r"\text{slope} = 0")   # the end of a curve

    def test_a_travelling_tangent_stops_at_a_corner(self):
        with self.assertRaisesRegex(plan.StoryboardError, "corner"):
            build(graph(expr="abs(x)", beats=marked(move={"from": -2, "to": 2, "tangent": True})))


class Areas(unittest.TestCase):
    def area(self, expr, lo, hi, **fields):
        return build(graph(expr=expr, beats=marked(shade={"from": lo, "to": hi}), **fields))["marks"][0]["tex"]

    def test_no_number_across_a_pole(self):
        for expr, lo, hi in [("1/x", -1, 2), ("1/x^2", -1, 2), ("tan(x)", 0, 3)]:
            with self.assertRaisesRegex(plan.StoryboardError, "without bound", msg=expr):
                self.area(expr, lo, hi, y=[-5, 10])
        self.assertTrue(math.isnan(plot.Formula("1/x").area(-1.0, 1.0)[0]))

    def test_areas(self):
        self.assertEqual(self.area("sin(x)", 0, "pi", x=["-2*pi", "2*pi"]), r"\text{area} = 2")
        self.assertEqual(self.area("sin(x)", 0, "2*pi", x=["-2*pi", "2*pi"]), r"\text{area} = 0")
        self.assertEqual(self.area("floor(x)", 0, 3), r"\text{area} \approx 3")
        self.assertEqual(self.area("exp(-(40*x)^2)", -1, 1, x=[-1, 1]), r"\text{area} \approx 0.04431")     # sqrt(pi)/40
        self.assertEqual(self.area("x^2", 0, 1), r"\text{area} \approx 0.3333")


class Numbers(unittest.TestCase):
    def test_a_tiny_value_is_not_called_zero_and_noise_is(self):
        point = lambda expr, at, **f: build(graph(expr=expr, beats=marked(point={"x": at}), **f))["marks"][0]["tex"]
        self.assertEqual(point("exp(-x)", 50, x=[0, 50]), r"\left(50,\ 1.929 \times 10^{-22}\right)")
        self.assertEqual(point("sin(x)", "pi", x=["-2*pi", "2*pi"]), r"\left(\pi,\ 0\right)")

    def test_axis_marks(self):
        ticks = lambda **f: [text for _, text in build(graph(**f))["xticks"]]
        self.assertEqual(ticks(expr="x", x=[0, 1e-9])[1:3], ["10⁻¹⁰", "2×10⁻¹⁰"])
        self.assertEqual(len(ticks(expr="sin(x)", x=["-500*pi", "500*pi"])), 11)       # it used to be 63, in a smear
        self.assertEqual(ticks(expr="sin(x)", x=["-pi/1000", "pi/1000"])[0], "−0.003")   # too small for pi: numbers
        self.assertEqual(ticks(expr="x^2", x=[1e8, 1e8 + 2]), ["100000000", "100000000.5", "100000001", "100000001.5", "100000002"])
        with self.assertRaisesRegex(plan.StoryboardError, "read the same"):
            build(graph(expr="x", x=[1e9, 1e9 + 1e-3]))

    def test_bad_values_are_named_not_crashed_on(self):
        for beat in [{"point": True}, {"point": {}}, {"tangent": 5}, {"shade": True}, {"move": 5}]:
            with self.assertRaisesRegex(plan.StoryboardError, "takes an object such as", msg=str(beat)):
                build(graph(expr="x^2", beats=marked(**beat)))


class Equations(unittest.TestCase):
    def test_what_cannot_be_traced_is_refused(self):
        for equation, why in [("(x^2 + y^2 - 1)^2 = 0", "touch without crossing"), ("abs(y - x^2) = 0", "touch without crossing"),
                              ("floor(x) = floor(y)", "whole region"), ("abs(x) = x", "whole region"), ("x = x", "whole region")]:
            with self.assertRaisesRegex(plan.StoryboardError, why, msg=equation):
                build(graph(curves=[{"equation": equation}], y=[-3, 3]))

    def test_a_step_in_an_equation_is_not_joined_up(self):
        treads = plot.Implicit("y = floor(x)").strokes(-3, 3, -3.5, 3.5)
        self.assertEqual(len(treads), 6)
        for tread in treads:
            self.assertLess(max(y for _, y in tread) - min(y for _, y in tread), 1e-6)


class Marks(unittest.TestCase):
    def shown(self, tex, **beat):
        return build(formulas(tex, **beat))["blocks"]

    def test_a_mark_is_a_term_not_a_letter_of_a_command(self):
        wrap = lambda piece: r"\htmlClass{idr-m0}{" + piece + "}"
        self.assertEqual(self.shown(r"\frac{a}{b}", mark={"line": 1, "tex": "a"}), [r"\frac{" + wrap("a") + "}{b}"])
        self.assertEqual(self.shown(r"\partial p", mark={"line": 1, "tex": "p"}), [r"\partial " + wrap("p")])
        self.assertEqual(self.shown(r"\int_0^n \sin(i)", mark={"line": 1, "tex": "i"}), [r"\int_0^n \sin(" + wrap("i") + ")"])
        self.assertEqual(self.shown(r"a \\ c", mark={"line": 1, "tex": "c"}), [r"a \\ " + wrap("c")])        # after a row break
        with self.assertRaisesRegex(plan.StoryboardError, r"inside the command \\frac"):
            self.shown(r"\frac{1}{2}", mark={"line": 1, "tex": "fr"})

    def test_which_one_and_exponents(self):
        wrap = lambda piece: r"\htmlClass{idr-m0}{" + piece + "}"
        self.assertEqual(self.shown("x^2 + 2x + 1", mark={"line": 1, "tex": "x", "nth": 2}), ["x^2 + 2" + wrap("x") + " + 1"])
        self.assertEqual(self.shown("x^2 + 2x + 1", mark={"line": 1, "tex": "2"}), ["x^{" + wrap("2") + "} + 2x + 1"])
        with self.assertRaisesRegex(plan.StoryboardError, "occurs 2 time"):
            self.shown("x^2 + 2x + 1", mark={"line": 1, "tex": "x", "nth": 3})
        with self.assertRaisesRegex(plan.StoryboardError, "runs past"):
            self.shown("x^{2} + 1", mark={"line": 1, "tex": "{2} +"})

    def test_a_mark_may_not_change_the_formula(self):
        rows = r"\begin{aligned} a &= b \\ c &= d \end{aligned}"
        for piece in (r"b \\ c", "&= b"):
            with self.assertRaisesRegex(plan.StoryboardError, "rows or columns"):
                self.shown(rows, mark={"line": 1, "tex": piece})
        with self.assertRaisesRegex(plan.StoryboardError, "cannot be highlighted on its own"):
            self.shown(r"\left( x \right)", mark={"line": 1, "tex": r"\left("})

    def test_the_same_term_can_be_marked_again(self):
        scene = formulas("a + b")
        scene["beats"] = [{"say": "one", "mark": {"line": 1, "tex": "a"}}, {"say": "two", "mark": None},
                          {"say": "three", "mark": {"line": 1, "tex": "a"}}]
        ops = [op["id"] for op in build(scene)["ops"] if op["op"] == "mark"]
        self.assertEqual(ops, [0, None, 0])

    def test_what_katex_would_only_show_as_an_error(self):
        for tex in (r"x + \htmlStyle{color:red}{y}", r"\href{https://example.com}{x}", r"\includegraphics{a.png}"):
            with self.assertRaisesRegex(plan.StoryboardError, "may contain", msg=tex):
                self.shown(tex)
        for tex in ("", "   ", 5):
            with self.assertRaisesRegex(plan.StoryboardError, "each formula is a string"):
                build({"type": "math", "heading": "h", "tex": [tex], "beats": [{"say": "one"}]})
