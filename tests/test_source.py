"""Tests for videos with no source, scenes that go past the source, and what the voice is given to say.

Run from the repository root:  python -m unittest discover tests
"""
import tempfile
import unittest
from pathlib import Path

from idr import plan, speech

CODE = {"type": "code", "heading": "h", "file": "a.py", "lines": [1, 2], "expect": "def f", "beats": [{"say": "one"}]}
FLOW = {"type": "flow", "heading": "h", "nodes": [{"label": "a"}, {"label": "b"}], "beats": [{"say": "one"}]}
STEPS = {"type": "steps", "heading": "h", "items": [{"title": "a"}], "beats": [{"say": "one"}]}


class Listening(plan.DryNarrator):
    """Records what the voice was asked to say."""

    def __init__(self):
        self.heard = []

    def say(self, text):
        self.heard.append(text)
        return super().say(text)


def build(chapters, narrator=None, settings=None, **top):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "a.py").write_text("def f():\n    return 1\n", encoding="utf-8")
        board = {"title": "t", "chapters": chapters, **top}
        return plan.build(board, root, "light", narrator or plan.DryNarrator(), pronounce=settings)[0]


def chapter(*scenes, **fields):
    return {"title": "c", "scenes": list(scenes), **fields}


class NoSource(unittest.TestCase):
    def test_a_video_shows_its_source_or_says_it_has_none(self):
        with self.assertRaisesRegex(plan.StoryboardError, "no scene shows a source"):
            build([chapter(FLOW)])
        scenes = build([chapter(FLOW)], source="none")
        self.assertEqual(scenes[0].payload["basis"], plan.NO_SOURCE)          # said on the opening card
        self.assertNotIn("basis", scenes[1].payload)
        self.assertNotIn("basis", build([chapter(CODE, FLOW)])[0].payload)

    def test_none_is_refused_when_a_source_is_shown(self):
        with self.assertRaisesRegex(plan.StoryboardError, "shows a source"):
            build([chapter(CODE, FLOW)], source="none")
        with self.assertRaisesRegex(plan.StoryboardError, 'can only be "none"'):
            build([chapter(CODE)], source="my head")

    def test_instructions_need_no_source(self):
        self.assertNotIn("basis", build([chapter(STEPS)])[0].payload)


class Beyond(unittest.TestCase):
    def test_a_scene_past_the_source_is_labelled(self):
        card, code, flow = build([chapter(CODE, {**FLOW, "beyond": True})])
        self.assertEqual([card.payload["beyond"], code.payload["beyond"], flow.payload["beyond"]], [False, False, True])

    def test_a_whole_chapter(self):
        scenes = build([chapter(CODE), chapter(FLOW, STEPS, beyond=True)])
        self.assertEqual([s.payload["beyond"] for s in scenes], [False, False, True, True, True])

    def test_the_source_itself_cannot_be_beyond(self):
        with self.assertRaisesRegex(plan.StoryboardError, "shows the source"):
            build([chapter({**CODE, "beyond": True})])
        with self.assertRaisesRegex(plan.StoryboardError, "shows the source"):
            build([chapter(CODE, FLOW, beyond=True)])

    def test_with_no_source_nothing_is_labelled(self):
        scenes = build([chapter({**FLOW, "beyond": True})], source="none")
        self.assertFalse(any(s.payload["beyond"] for s in scenes))

    def test_an_example_is_not_the_source(self):
        example = {**CODE, "example": True}
        _, code, shown = build([chapter(CODE, example)])
        self.assertEqual(shown.payload["sub"], plan.EXAMPLE_SUB)             # no file name: it is not the user's file
        self.assertTrue(shown.payload["beyond"])
        self.assertIn("a.py", code.payload["sub"])
        with self.assertRaisesRegex(plan.StoryboardError, "no scene shows a source"):
            build([chapter(example)])                                          # an example alone is not a source
        self.assertEqual(build([chapter(example)], source="none")[-1].payload["sub"], plan.EXAMPLE_SUB)
        with self.assertRaisesRegex(plan.StoryboardError, 'no "ref"'):
            build([chapter(CODE, {**example, "ref": "HEAD"})])

    def test_an_example_is_read_from_beside_the_storyboard(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as work:
            (Path(src) / "a.py").write_text("def f():\n    return 1\n", encoding="utf-8")
            (Path(work) / "demo.py").write_text("def g():\n    return 2\n", encoding="utf-8")
            demo = {**CODE, "file": "demo.py", "expect": "def g", "example": True}
            board = {"title": "t", "chapters": [chapter(CODE, demo)]}
            scenes, _ = plan.build(board, Path(src), "light", plan.DryNarrator(), home=Path(work))
            self.assertEqual(scenes[-1].payload["rows"][0]["plain"], "def g():")


class Speech(unittest.TestCase):
    def test_letter_ordinals(self):
        cases = {"the n-th derivative": "the enth derivative", "The i-th and j-th rows": "The eyeth and jayth rows",
                 "the nth time": "the enth time", "K-th": "kayth", "the (n+1)-th term": "the n plus first term",
                 "the (k-1)th step": "the k minus first step", "n+2-th": "n plus second"}
        for written, said in cases.items():
            self.assertEqual(speech.spoken(written), said)

    def test_ordinary_words_are_left_alone(self):
        for text in ["a month of width and depth", "Seth and Beth", "o-th", "length-th", "don'th"]:
            self.assertEqual(speech.spoken(text), text)

    def test_notation_is_read_aloud(self):
        cases = {"a - b is small": "eigh minus b is small",                  # the voice dropped the minus
                 "the n-1 case": "the n minus 1 case",
                 "x \u2208 \u211d": "x in the real numbers",                 # both signs were silent
                 "x \u2192 0": "x goes to 0",
                 "f'(x) is positive": "f prime of x is positive",
                 "f(x) = x^2 + 1": "f of x = x squared + 1",
                 "so x\u00b2 wins": "so x squared wins",
                 "|x| < 1": "the absolute value of x is less than 1",
                 "10^-3": "10 to the minus 3", "e^x": "e to the x", "x_i": "x sub i",
                 "the slope is 1/2": "the slope is one half", "1/x": "1 over x", "dy/dx": "dee why by dx",
                 "\u2202f/\u2202x": "partial f by partial x", "n!": "n factorial", "0 < x < 1": "0 is less than x is less than 1",
                 "Here |x| < 1. Then x - 1.5 is negative.": "Here the absolute value of x is less than 1. Then x minus 1.5 is negative.",
                 "2\u03c0r": "2 \u03c0 r", "sin(x)": "sine of x", "sin x plus cos x": "sine x plus cos x",
                 "sqrt(2x)": "the square root of 2x", "the 0-th term": "the 0th term", "1e-6": "10 to the minus 6"}
        for written, said in cases.items():
            self.assertEqual(speech.spoken(written), said)

    def test_names_and_terms(self):
        cases = {"Cauchy's theorem": "koh-shee's theorem", "Poincar\u00e9": "poo-ahn-kah-ray", "an eigenvalue": "an eye-gun-value",
                 "sinh and tanh": "sinch and tanch", "xi": "\u03be", "QED": "Q E D", "w.r.t. x": "with respect to x",
                 "the Lagrangian": "the luh-grahn-jee-un", "dy over dx": "dee why over dx"}
        for written, said in cases.items():
            self.assertEqual(speech.spoken(written), said)

    def test_the_letter_a_is_not_the_article(self):
        cases = {"Around a point a, the first term copies the height.": "Around a point eigh, the first term copies the height.",
                 "x minus a to the n": "x minus eigh to the n", "a plus b": "eigh plus b", "f of a": "f of eigh",
                 "A is a matrix": "eigh is a matrix", "a squared plus b squared": "eigh squared plus b squared"}
        for written, said in cases.items():
            self.assertEqual(speech.spoken(written), said)
        for text in ["Add a squared term", "a prime number", "a plus sign", "It runs a for loop", "a to-do list", "what a day",
                     "a by-product", "a times table", "half a second"]:
            self.assertEqual(speech.spoken(text), text)

    def test_prose_and_code_are_left_alone(self):
        for text in ["the x-y plane", "a - well - b", "the 'a' key", "it's y'all", "wow!", "I/O", "24/7", "m/s", "Vec<T>",
                     "It calls parse_args() first.", "see src/main.py", "x = 2", "x \u2264 1", "e.g. this"]:
            self.assertEqual(speech.spoken(text), text)

    def test_what_still_cannot_be_said_is_warned_about(self):
        self.assertIsNone(speech.trouble("so x^2 is less than x when |x| < 1, and a - b \u2208 \u211d"))
        self.assertIsNone(speech.trouble("x = 2"))
        self.assertIn("cannot read \u2016", speech.trouble("\u2016x\u2016 is the norm"))
        for text in ["It calls parse_args() first.", "see src/main.py", "x^(n+1)", "Vec<T>", "x=2"]:
            self.assertIn("code-like", speech.trouble(text), msg=text)
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "a.py").write_text("def f():\n    return 1\n", encoding="utf-8")
            board = {"title": "t", "chapters": [chapter(CODE, {**FLOW, "beats": [{"say": "Here \u2016x\u2016 is the norm."}]})]}
            _, warnings = plan.build(board, Path(tmp), "light", plan.DryNarrator())
        self.assertTrue(any("the voice cannot read" in w for w in warnings))

    def test_the_storyboard_can_name_its_own(self):
        table = {"PyPI": "pie pee eye", "PyPI JSON": "pie pee eye jason"}
        self.assertEqual(speech.spoken("PyPI and PyPI JSON, not PyPIx", table), "pie pee eye and pie pee eye jason, not PyPIx")

    def test_the_voice_gets_the_respelling_and_the_caption_does_not(self):
        voice = Listening()
        flow = {**FLOW, "beats": [{"say": "The n-th node talks to memtable."}]}
        scenes = build([chapter(CODE, flow)], narrator=voice, settings={"memtable": "mem table"},
                       pronounce={"node": "nohd"})
        self.assertIn("The enth nohd talks to mem table.", voice.heard)
        self.assertEqual(scenes[-1].payload["captions"][0]["text"], "The n-th node talks to memtable.")

    def test_a_bad_table_is_refused(self):
        with self.assertRaisesRegex(plan.StoryboardError, "pronounce"):
            build([chapter(CODE)], pronounce=["PyPI"])
