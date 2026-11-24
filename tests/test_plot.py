"""Tests for plot scenes: the formula reader, what it refuses, and the numbers the engine works out.

Run from the repository root:  python -m unittest discover tests
"""
import math
import tempfile
import unittest
from pathlib import Path

from idr import plan, plot


def build(scene, **top):
    with tempfile.TemporaryDirectory() as tmp:
        board = {"title": "t", "chapters": [{"title": "c", "scenes": [scene]}], **top}
        built, warnings = plan.build(board, Path(tmp), "light", plan.DryNarrator())
        return built[-1].payload, warnings


def scene(**fields):
    return {"type": "plot", "heading": "h", "x": [-3, 3], "beats": [{"say": "one"}], **fields}


class Formulas(unittest.TestCase):
    def test_values(self):
        self.assertEqual(plot.Formula("x^2")(3.0), 9.0)
        self.assertEqual(plot.Formula("-x^2")(3.0), -9.0)                # the minus applies to the square
        self.assertAlmostEqual(plot.Formula("2*sin(pi/2) + e^0")(0.0), 3.0)
        self.assertAlmostEqual(plot.Formula("log2(1/x)")(8.0), -3.0)

    def test_no_value_is_nan(self):
        self.assertTrue(math.isnan(plot.Formula("sqrt(x)")(-1.0)))
        self.assertTrue(math.isnan(plot.Formula("1/x")(0.0)))
        self.assertTrue(math.isnan(plot.Formula("ln(x)")(0.0)))

    def test_latex_comes_from_the_same_formula(self):
        cases = {"x^2": "x^{2}", "2*x + 1": "2x + 1", "x*x": r"x \cdot x", "2*(3*x)": r"2 \cdot 3x",
                 "2*3^x": r"2 \cdot 3^{x}", "1/x": r"\frac{1}{x}", "(x+1)^2": r"\left(x + 1\right)^{2}",
                 "x - (2 - x)": r"x - \left(2 - x\right)", "sqrt(1 - x^2)": r"\sqrt{1 - x^{2}}",
                 "exp(-x)": "e^{-x}", "2^-x": "2^{-x}", "x + -2": r"x + \left(-2\right)"}
        for text, tex in cases.items():
            self.assertEqual(plot.Formula(text).tex(), tex, text)

    def test_only_arithmetic_is_read(self):
        for text in ["__import__('os').system('id')", "x.real", "y^2", "2x", "x if x else 1", "[x]", "lambda: 1",
                     "foo(x)", "sin(x, 2)", "x**'a'", "(x := 2)", "x; x", "open('f')", "", "x" * 201]:
            with self.assertRaises(ValueError, msg=text):
                plot.Formula(text)

    def test_huge_powers_do_not_hang(self):
        self.assertTrue(math.isnan(plot.Formula("9^9^9^9")(1.0)))

    def test_slope_and_area(self):
        f = plot.Formula("x^2")
        self.assertAlmostEqual(f.slope(2.0, 6.0), 4.0, places=6)
        self.assertAlmostEqual(f.area(0.0, 2.0), 8 / 3, places=9)
        self.assertTrue(math.isnan(plot.Formula("1/x").area(-1.0, 1.0)))

    def test_numbers(self):
        self.assertEqual([plot.number(v) for v in (4.0, 8 / 3, -0.5, 1234.5678, 0.000123456, -1e-15)],
                         ["4", "2.667", "-0.5", "1235", "0.0001235", "0"])
        self.assertFalse(plot.rounded(4.0 - 1e-11))
        self.assertTrue(plot.rounded(8 / 3))

    def test_ticks(self):
        self.assertEqual(plot.ticks(-3, 3), [-3, -2, -1, 0, 1, 2, 3])
        self.assertEqual(plot.ticks(0, 9.6), [0, 2, 4, 6, 8])

    def test_lines_stop_at_gaps_and_jumps(self):
        self.assertEqual(len(plot.strokes(plot.Formula("1/x"), -3, 3, -5, 5)), 2)
        self.assertEqual(len(plot.strokes(plot.Formula("tan(x)"), -4, 4, -5, 5)), 3)
        half = plot.strokes(plot.Formula("sqrt(4 - x^2)"), -4, 4, -3, 3)
        self.assertEqual(len(half), 1)
        self.assertAlmostEqual(half[0][0][0], -2.0, places=4)             # the curve reaches the end of its domain
        self.assertAlmostEqual(half[0][-1][0], 2.0, places=4)


class Scenes(unittest.TestCase):
    def test_label_and_marks_are_computed(self):
        p, warnings = build(scene(expr="x^2", name="f", beats=[
            {"say": "a", "reveal": 1},
            {"say": "b", "point": {"x": 2}, "tangent": {"x": 2}},
            {"say": "c", "shade": {"from": 0, "to": 2}}]))
        self.assertEqual(warnings, [])
        self.assertEqual(p["curves"][0]["tex"], "f(x) = x^{2}")
        point, tangent, shade = p["marks"]
        self.assertEqual((point["x"], point["y"]), (2.0, 4.0))
        self.assertIn(r"\left(2,\ 4\right)", point["tex"])
        self.assertEqual(tangent["tex"], r"\text{slope} = 4")
        self.assertEqual(shade["tex"], r"\text{area} \approx 2.667")

    def test_a_new_mark_replaces_the_last_of_its_kind(self):
        p, _ = build(scene(expr="x^2", beats=[{"say": "a", "point": {"x": 1}}, {"say": "b", "point": {"x": 2}},
                                              {"say": "c", "point": None}]))
        ops = [(op["op"], op["mark"]) for op in p["ops"] if op["op"] in ("show", "hide")]
        self.assertEqual(ops, [("show", 0), ("hide", 0), ("show", 1), ("hide", 1)])

    def test_three_curves_at_most(self):
        build(scene(curves=["x", "x^2", "x^3"]))
        with self.assertRaises(plan.StoryboardError):
            build(scene(curves=["x", "x^2", "x^3", "x^4"]))

    def test_refusals(self):
        for fields in [{"expr": "import os"}, {"expr": "x^2", "x": [3, -3]}, {"expr": "x^2", "x": None},
                       {"expr": "sqrt(x)", "x": [-3, -1]},                                       # never has a value
                       {"expr": "x^2", "name": "func"},
                       {"expr": "x^2", "beats": [{"say": "a", "point": {"x": 5}}]},              # outside x
                       {"expr": "x^2", "y": [0, 2], "beats": [{"say": "a", "point": {"x": 2}}]},  # outside y
                       {"expr": "1/x", "beats": [{"say": "a", "point": {"x": 0}}]},              # no value there
                       {"expr": "1/x", "y": [-9, 9], "beats": [{"say": "a", "shade": {"from": -1, "to": 1}}]},
                       {"expr": "x^2", "beats": [{"say": "a", "tangent": {"x": 1, "on": 2}}]}]:
            with self.assertRaises(plan.StoryboardError, msg=str(fields)):
                build(scene(**fields))

    def test_numbers_may_be_written_with_pi(self):
        p, _ = build(scene(expr="sin(x)", x=["-2*pi", "2*pi"], beats=[{"say": "a", "point": {"x": "pi/2"}}]))
        self.assertAlmostEqual(p["x"][1], 2 * math.pi)
        self.assertEqual([label for _, label in p["xticks"]],
                         ["\u22122π", "\u22123π/2", "\u2212π", "\u2212π/2", "0", "π/2", "π", "3π/2", "2π"])
        self.assertEqual(p["marks"][0]["tex"], r"\left(\frac{\pi}{2},\ 1\right)")
        numbered, _ = build(scene(expr="sin(x)", x=["-2*pi", "2*pi"], xticks="numbers"))
        self.assertEqual(numbered["xticks"][0][1], "\u22126")

    def test_parameter_curve(self):
        p, _ = build(scene(curves=[{"x": "2*cos(t)", "y": "2*sin(t)", "t": [0, "2*pi"]}], y=[-3, 3], beats=[
            {"say": "a", "point": {"t": 0}, "tangent": {"t": "pi/2"}}]))
        self.assertEqual(p["curves"][0]["draw"], "trace")
        point, tangent = p["marks"]
        self.assertEqual((point["x"], point["y"]), (2.0, 0.0))
        self.assertEqual(tangent["tex"], r"\text{slope} = 0")
        upright, _ = build(scene(curves=[{"x": "2*cos(t)", "y": "2*sin(t)", "t": [0, "2*pi"]}], y=[-3, 3],
                                 beats=[{"say": "a", "tangent": {"t": 0}}]))
        self.assertEqual(upright["marks"][0]["tex"], r"\text{vertical}")

    def test_equation(self):
        circle = plot.Implicit("x^2 + y^2 = 4")
        lines = circle.strokes(-4, 4, -3, 3)
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0][0], lines[0][-1])                         # a closed loop
        for x, y in lines[0]:
            self.assertAlmostEqual(math.hypot(x, y), 2.0, places=3)
        self.assertEqual(len(plot.Implicit("x*y = 1").strokes(-4, 4, -3, 3)), 2)
        self.assertEqual(len(plot.Implicit("y = tan(x)").strokes(-4, 4, -5, 5)), 3)   # no lines up the asymptotes
        p, _ = build(scene(curves=[{"equation": "x^2 + y^2 = 4"}], y=[-3, 3], equal=True, beats=[
            {"say": "a", "point": {"x": 0, "y": 2}, "tangent": {"x": "sqrt(2)", "y": "sqrt(2)"}}]))
        self.assertTrue(p["equal"])
        self.assertEqual(p["curves"][0]["tex"], "x^{2} + y^{2} = 4")
        self.assertEqual(p["marks"][1]["tex"], r"\text{slope} = -1")

    def test_travelling_point(self):
        p, _ = build(scene(expr="x^2", beats=[{"say": "a", "move": {"from": -2, "to": 2, "tangent": True}},
                                              {"say": "b", "point": {"x": 0}}]))
        steps = p["marks"][0]["steps"]
        self.assertEqual(len(steps), plan.MOVE_STEPS + 1)
        self.assertEqual(steps[0][4:], ["(\u22122.00, 4.00)", "slope \u22124.00"])
        self.assertEqual(steps[-1][4:], ["(2.00, 4.00)", "slope 4.00"])
        for x, y, dx, dy, _, _ in steps:                                    # every position is on the curve
            self.assertAlmostEqual(y, x * x, places=5)
            self.assertAlmostEqual(dy / dx, 2 * x, places=5)
        ops = [(op["op"], op["mark"]) for op in p["ops"] if op["op"] in ("show", "hide", "travel")]
        self.assertEqual(ops, [("show", 0), ("travel", 0), ("hide", 0), ("show", 1)])
        travel = next(op for op in p["ops"] if op["op"] == "travel")
        self.assertGreaterEqual(p["ops"][-1]["t"], travel["t"] + travel["dur"])   # the next beat waits for it

    def test_more_refusals(self):
        for fields in [{"curves": [{"equation": "x^2 + y^2"}], "y": [-3, 3]},                          # no = sign
                       {"curves": [{"equation": "x^2 + y^2 = 4"}]},                                    # needs y
                       {"curves": [{"equation": "x^2 + y^2 = 4"}], "y": [-3, 3],
                        "beats": [{"say": "a", "point": {"x": 1, "y": 1}}]},                           # not on it
                       {"curves": [{"equation": "x^2 + y^2 = 4"}], "y": [-3, 3],
                        "beats": [{"say": "a", "shade": {"from": 0, "to": 1}}]},
                       {"curves": [{"equation": "x^2 + y^2 = 4"}], "y": [-3, 3],
                        "beats": [{"say": "a", "move": {"from": 0, "to": 1}}]},
                       {"curves": [{"x": "cos(t)", "t": [0, 1]}]},                                     # no y(t)
                       {"curves": [{"x": "cos(t)", "y": "sin(u)", "t": [0, 1]}]},                      # unknown variable
                       {"curves": [{"x": "cos(t)", "y": "sin(t)", "t": [0, 1]}],
                        "beats": [{"say": "a", "point": {"t": 2}}]},                                   # outside t
                       {"expr": "x^2", "x": ["-2*pi", "os"]},
                       {"expr": "x^2", "xticks": "tau"},
                       {"expr": "x^2", "beats": [{"say": "a", "move": {"from": 0, "to": 5}}]},          # leaves the graph
                       {"expr": "1/x", "y": [-9, 9], "beats": [{"say": "a", "move": {"from": -1, "to": 1}}]}]:
            with self.assertRaises(plan.StoryboardError, msg=str(fields)):
                build(scene(**fields))

    def test_labels_are_checked_as_latex(self):
        p, _ = build(scene(curves=["exp(-x^2/2)/sqrt(2*pi)", "abs(x)^(1/3)", "floor(x) + log10(x + 4)"]))
        self.assertEqual(len(p["curves"]), 3)                           # build() fails on LaTeX KaTeX cannot parse


if __name__ == "__main__":
    unittest.main()
