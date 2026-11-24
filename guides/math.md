# Mathematics: formulas and graphs

Part of the instructions in `SKILL.md`. Read this before you write a `math` or `plot` scene, or make a video
from a source that is mathematics: a paper with equations, a proof, a derivation, a topic such as the chain
rule. Everything in `SKILL.md` still applies; this file adds what those two scenes take and what they refuse.

For how formulas are said aloud, read `voice.md` beside this file.

## 1. Formulas: the `math` scene

Use it when a formula is the point: from the source, or one you write to explain it.

- **Fields.** From the source: `file` (`.tex` or `.md`), `lines: [first, last]`, `expect`, optional `ref`. The range's display math (`$$...$$`, `\[...\]`, `equation`/`align`/`gather` environments) is shown as written, with the equation numbers the paper prints (worked out from the file; when they cannot be, none is shown and the check says so). Written for the video: `tex`, a list of LaTeX formulas, one per line. 1 to 4 formulas.
- **What a beat can do.** `reveal`: how many formulas are visible from now on. `mark`: `{ "line": n, "tex": "part of that formula's LaTeX" }` (or a list) runs a marker over that term; `"nth": 2` picks the second place the piece occurs; `null` clears all marks, and the same term can be marked again later. `note`: a short label beside the latest mark.

```json
{ "type": "math", "heading": "The descent lemma", "file": "paper.tex", "lines": [28, 30], "expect": "\\begin{equation}",
  "beats": [
    { "say": "One step lowers f by at least this much.", "reveal": 1 },
    { "say": "The factor in front is positive only for a small enough step.",
      "mark": { "line": 1, "tex": "\\eta" }, "note": "step size" } ] }
```

**Math in any text.** Write `$...$` for inline math and `$$...$$` for display math in headings, `quote` text, `table` cells and `flow`, `compare`, `stats` and `steps` text; it is typeset with KaTeX. A dollar sign counts as math only by Pandoc's rule (an opening `$` followed by a non-space, a closing `$` after a non-space and not before a digit), so `$5 to $10` and `$HOME` stay plain text; write `\$` for a literal dollar where the rule would misread it. LaTeX that does not parse is shown as the plain text it is, with a warning. `"math": false` on a scene (or at the top of the storyboard) turns this off. In a `quote`, a `mark` may cover whole `$...$` expressions but may not start or end inside one; to mark a term inside a formula, use a `math` scene.

**Limits the check enforces.** 1 to 4 formulas per scene. Every formula is parsed with KaTeX by `check`; one that does not parse is an error, and so is `\href`, `\includegraphics` or `\htmlStyle`. A formula read from a `.tex` file may use the paper's own commands: `\newcommand`, `\def` and `\DeclareMathOperator` are read from that file and from the files it pulls in from beside it. Commands with an optional argument (`\newcommand{\half}[1][1]{...}`) are written out for you. A `mark` on such a formula is copied from the file, with the paper's own commands. `\cite` and `\ref` inside a formula do not parse: show that formula with `tex`, written out, and say in `sub` where it is from. In a formula of your own, `\tag{3}` prints (3) beside it. A `mark` is a whole term: it may not start or stop inside a command name, run across `&` or `\\`, or take half of a `\left( ... \right)` pair. `check` lays every formula and graph out with the real fonts, and a formula wider or taller than the frame at the smallest size is an error: split it. A word of five letters or more written as math (`energy = mass`) is warned about: put words in `\text{...}`.

**From a paper.** A table in a `.tex` file is read by a `table` scene: give `lines` from the `\begin{tabular}` line to its `\end` line. `quote` and `table` scenes that read a `.tex` file typeset its inline math with the paper's own commands too.

## 2. Graphs: the `plot` scene

Use it when the source is about mathematics, and the shape of a curve is the point.

- **Fields.** `expr`: a formula in `x`, or `curves`: 1 to 3 curves (the kinds are listed under **Graphs** below). `x: [from, to]`. Optional `y: [from, to]` (chosen from the curves if left out; required when every curve is an equation), `equal: true`, `asymptotes`, `xticks`/`yticks`, `xlabel`, `ylabel` (short), and `source` for a credit line (where the function is from: the paper, the page; leave it out when the function is your own example in a video with no source).
- **What a beat can do.** `reveal`: how many curves are drawn from now on. On a curve: `point`, `tangent`, `secant`, `shade`, `riemann`, `arrow`, `move`. For a curve that changes: `stage`, `sweep`. Each mark takes `"on": n` for the n-th curve and `"as": "name"`, takes a list, stays until the next one of its kind, and is cleared by `null`.

A `plot` scene is for mathematics: a function the source defines or reasons about, when seeing its shape, a slope or an area makes the point. Write the formula the way a calculator takes it: `x^2`, `2*x + 1`, `exp(-x^2/2)`, `log2(1/x)`, `sqrt(1 - x^2)`, with `*` for every product and `pi`, `e`, `tau` as constants. The label on screen is typeset from that same formula, and every coordinate, slope, area and sum is computed from it. It does not draw data. If the source has a chart, show that chart with an `image` scene; if it has only numbers, show them in a `table` or `stats` scene. Do not make a chart the source does not have. `examples/calculus/storyboard.json` and `examples/area/storyboard.json` between them use everything below.

**Never type a number the engine works out.** Not in a label (there is nowhere to), and not in the narration: quote it. In `say`, `{slope}`, `{area}`, `{sum}`, `{x}` and `{y}` stand for the number shown by the one mark that sentence makes; when a sentence makes several, name them with `"as"` and write `{p.y}`. A label shows four significant figures; `"digits": 2` on the mark rounds the label and what the narration quotes together (`"shade": { "from": 0, "to": 2, "digits": 2 }` shows and says 2.7). A name is a letter followed by letters or digits. The voice and the caption then say exactly what the screen shows: `"say": "The slope there is {slope}.", "tangent": { "x": 1.5 }`.

The kinds of curve:

| Curve | Written as | Marks are placed by |
|---|---|---|
| A function of x | `"sin(x)"`, or `{ "expr": "x^2", "name": "f" }` (`name` is one letter, as in f for f(x)) | `x` |
| A curve in a parameter | `{ "x": "cos(t)", "y": "sin(t)", "t": [0, "2*pi"] }` | `t` |
| A polar curve | `{ "r": "1 + cos(theta)", "theta": [0, "2*pi"] }` | `t`, the angle |
| An equation | `{ "equation": "x^2 + y^2 = 4" }` | `x` and `y` of a point on it, which the check verifies |
| The area under another curve | `{ "integral": 1, "from": 0, "name": "A" }`: the area under curve 1 from x = 0 to x, added up by the engine. Curve 1 must come before it and be a function of x | `x` |
| A curve that moves through formulas | `{ "stages": ["x", "x - x^3/6", "x - x^3/6 + x^5/120"] }` (2 to 8) | no marks |
| A curve with a number that sweeps | `{ "expr": "sin(k*x)", "vary": { "k": [1, 4] } }` | no marks |

What a beat can put on a curve (functions of x take all of them; the others take `point`, `tangent` and, except equations, `arrow` and `move`):

| Action | Example | Shows |
|---|---|---|
| `point` | `{ "x": 2 }` | the point and its coordinates |
| | `{ "root": [1, 2.5] }`, `{ "max": [-2, 0] }`, `{ "min": [0, 2] }`, `{ "meet": 2, "near": [1, 2.5] }` | the same, at a place the engine finds: where the curve crosses zero, is highest or lowest in that range, or meets curve 2. `tangent` takes these too |
| `tangent` | `{ "x": 2 }` | the tangent line and its slope |
| `secant` | `{ "x": 1, "other": 3 }` | the line through two points of the curve and its slope |
| | `{ "x": 1, "other": 3, "approach": true }` | the second point slides to the first, and the line ends as the tangent |
| `shade` | `{ "from": 0, "to": 2 }` | the area down to the x axis, and its value |
| | `{ "from": 0, "to": 2, "between": [1, 2] }` | the area between curves 1 and 2 |
| | `{ "from": 0, "to": 6, "grow": true }` | the area fills in from its left edge while its value counts up |
| `riemann` | `{ "from": 0, "to": 2, "n": 8 }` | n rectangles and their sum; `"rule"` is `"left"` (the default), `"right"` or `"mid"`. Step n up with cues to show the sums closing in |
| `arrow` | `{ "from": 1, "to": -1.4 }` | an arrow from one point of the curve straight to another: a jump, a step of an iteration. A list draws a chain |
| `move` | `{ "from": -2, "to": 2, "tangent": true }` | a point that travels along the curve, with its tangent if asked |
| `stage` | `3` | a curve with `stages` moves to its third formula |
| `sweep` | `true`, or `{ "seconds": 4 }` | a curve with `vary` runs its number from the first value to the last |

Marks given together, in one beat or one cue, are shown together: a `shade` and a `riemann` with n = 1 side by side, or a list of points. A later beat or cue replaces what is there of its kind: a new `tangent` or `secant` replaces the line, a new `shade` or `riemann` the filled region, a new `point` the points, a new `arrow` the arrows. To keep an earlier mark, list it again exactly as it was beside the new one. A mark on the beat that reveals its curve appears once the curve has been drawn. A `move` counts as a new `point`, on whichever curve it is: it takes down the points that are there, and with `"tangent": true` the line too. To keep a point in view while another travels, give it its own `move` over the same range in the same list.

- **Labels.** A point's label gives both coordinates, and dotted lines lead from the point to both axes. With `"label": "x"` only the line down to the x axis is drawn, and with `"y"` only the line across to the y axis, so two such points can mark the edges of a strip. `"label": "x"` or `"y"` gives one (`x = 1.96`), and `"label": "none"` on a point, tangent, secant, area or sum leaves the label off; the narration can then quote only what is still shown. When labels crowd each other or cover what they point at, `"side": "left"`, `"right"`, `"above"` or `"below"` on a point or tangent says where its label sits. These go on the marks named here and nowhere else: a travelling point, an arrow, an area and a sum place their own labels, and a field a mark does not take is an error.
- **Never type a curve you could ask for.** The area function of a curve is `{ "integral": n, "from": a }`, not an antiderivative you worked out by hand: a slip in yours would be drawn as confidently as the truth. Put a tangent on it and a point on the original at the same x, and the slope and the height come out equal on screen, which is the fundamental theorem shown, not asserted.
- **Numbers with pi.** Anywhere a plot takes a number (`x`, `y`, `t`, a point, a shaded range) it also takes a constant expression in quotes: `"pi/2"`, `"2*pi"`, `"sqrt(2)"`. When `x` or `y` is written with pi, that axis is marked in fractions of pi and a point's label says $\pi/2$ instead of 1.571; `"xticks": "numbers"` or `"pi"` overrides the choice.
- **Round circles.** By default each axis is stretched to fill the frame. `"equal": true` makes one unit the same length on both axes, as geometry needs (circles, polar curves); then pick `x` about three times as wide as `y` in the wide format so the graph still fills the frame.
- **Asymptotes.** `"asymptotes": [{ "x": 1 }, { "y": 0 }]` draws dashed lines. They are checked first: a curve must shoot off at that x, or close in on that y towards an end of the x range.
- **What it will not draw.** The engine checks its own picture and refuses rather than draw something false: a curve that swings too fast for the x range (`sin(5000*x)` over six units; narrow `x`), a tangent at a corner, a jump or a crossing (`abs(x)` at 0), an area across a pole (`1/x` from -1 to 2, as a shade or as an `integral` curve), an equation whose sides only touch (`(x^2+y^2-1)^2 = 0`; drop the square) or that holds over a whole region (`floor(x) = floor(y)`), a root where there are several in the range, a stage of a changing curve with a pole. The message says which; change the scene, do not work around it. For a cube root of a negative number write `cbrt(x)`: `x^(1/3)` has no value there.
- **Things that take time.** `move`, an approaching `secant`, a growing `shade` and `sweep` take as long as the rest of their sentence (or `"seconds"`), and the scene waits for them to finish. A travelling point's label shows its coordinates, and its slope if it carries a line, to two decimals as it goes. Put `"at"` on the beat, or the action in a cue, to start it on a word. Moves in one list travel together. A `move` in a cue takes the place of one that began earlier in the sentence, wherever that one has got to, so give the first `"seconds"` short enough to arrive before the cue's word. A growing `shade` is quoted in the narration at its final value.

**Limits the check enforces.** 1 to 3 curves. A formula may use numbers, its variable (`x`; `t` in a parameter curve; `theta` in a polar curve; `x` and `y` in an equation; `x` and the one letter under `vary`), `+ - * / ^`, parentheses, `pi`, `e`, `tau` and the functions `sin cos tan asin acos atan sinh cosh tanh exp ln log log2 log10 sqrt cbrt abs floor ceil`; anything else is an error. An equation has exactly one `=`. A point, tangent, secant, shaded area, Riemann sum, arrow or travelling point must stay inside the graph, and a point given for an equation must satisfy it. A Riemann sum has 1 to 200 rectangles. Axis names are up to 24 characters. A `{...}` in the narration must name a number a mark of that scene shows.

## 3. Staying truthful with mathematics

- A `math` or `table` scene with `file` shows only what is in the file at those lines, as a `code` or `quote` scene does: the LaTeX and the cells are shown as the file has them. (What changes is what LaTeX itself would change: `\label{...}` is dropped, an equation gets the number the paper prints, and in a LaTeX table `$-0.8$` is shown as the number −0.8 and `\textbf{...}` as its text.) If the source writes a formula as plain text, like `log2 1/p`, do not present your LaTeX version of it as the source: write it in a `math` scene with `tex`, which is shown as an explanation, with no file line.
- A `math` or `table` scene with `tex` or `header` is your explanation. Every value in a written table must come from the source, as in `stats`; name where in `source`.
- A number a graph works out (a slope, an area, a sum, a coordinate) is quoted in the narration with `{...}`, never retyped: a retyped number can disagree with the screen, and nothing would notice.
- A `plot` scene is your explanation too. Plot a function the source gives or is plainly about, and say where it is from in `source`. Its points, slopes and areas are worked out by the engine from the formula, so they are exact for what is drawn; they are not a claim the source made unless the source says so.
