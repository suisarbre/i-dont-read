# Diagrams, rows of cells, sequences and charts

Part of the instructions in `SKILL.md`. Read this before you write a `diagram`, `array`, `sequence` or `chart`
scene. Everything in `SKILL.md` still applies; this file adds what those four scenes take and what they refuse.

The first three are your explanation of the source, like a `flow` or `compare` scene: use them beside the code
or text they explain, not in place of it. A `chart` is different: it is drawn from a file of the source, and
counts as showing the source.

`examples/cache/storyboard.json` uses all four.

## 1. A diagram with branches: `diagram`

Use it when the parts do not form one line: a state machine, a decision with two outcomes, modules that depend
on each other, a loop. (For a straight chain of 2 to 6 steps, `flow` is simpler and larger on screen.)

```json
{ "type": "diagram", "heading": "Hit or miss",
  "nodes": [ { "id": "cached", "label": "In the row?" }, { "id": "fresh", "label": "Still fresh?" },
             { "id": "hit", "label": "Hit", "desc": "move to the back" }, { "id": "load", "label": "Miss" } ],
  "edges": [ { "from": "cached", "to": "fresh", "label": "yes" }, { "from": "cached", "to": "load", "label": "no" },
             { "from": "fresh", "to": "hit", "label": "yes" }, { "from": "fresh", "to": "load", "label": "expired" } ],
  "beats": [
    { "say": "A lookup first asks whether the key is there.", "reveal": 1, "focus": "cached" },
    { "say": "A missing key and an expired one end the same way.", "reveal": 4,
      "follow": [["cached", "load"], ["fresh", "load"]], "focus": "load" } ] }
```

- **Fields.** `nodes`: 2 to 10, each `{ "id", "label", "desc" }` (`id` is what edges and beats call it; left out, it is the label; `desc` is small print under the label, up to 36 characters). `edges`: each `{ "from", "to", "label", "dashed" }`, by node id (`"dashed": true` draws a broken line); an edge from a node to itself draws a loop on a side of the box with no neighbour (when both sides have one, the loop is squeezed between them and has room for a label of one short word). `direction`: `"right"` (the default in a wide frame) or `"down"` (the default in a tall one).
- **What a beat can do.** `reveal`: how many nodes, in the order listed, are visible from now on; an arrow appears once both its ends are there. Reveal every node you list: what the beats leave out appears as the scene ends, with no sentence about it, and the check warns. `focus`: a node id, or a list, gets the ring. `follow`: an edge written `["from", "to"]`, or a list of them, is drawn in the accent colour: a path being walked. `focus` and `follow` last for their sentence, and name only what is already on screen: a beat that points at a node it has not revealed is an error. `reveal` only goes up; it cannot hide a node again. `cues` work as in any scene.
- **You do not place anything.** The engine puts the nodes in layers so that arrows point forward, draws an arrow that closes a loop pointing back, takes an arrow that skips a layer round the boxes of that layer, and sorts each layer so arrows cross as little as possible. Arrows that bend in the same gap each turn at a place of their own, so two arrows between the same two boxes, there and back, are drawn apart, each with its own label. List the nodes in the order you will reveal them; that order also breaks ties.
- **Limits the check enforces.** An edge or a beat that names a node that does not exist, two nodes with one id, an edge listed twice, and a `follow` along an arrow that was never drawn are errors. So is a diagram too long or too wide for the frame: a wide frame drawn rightwards holds 6 layers of up to 4 nodes (drawn downwards, 4 layers of up to 6), a tall frame drawn downwards 7 layers of up to 3 (drawn rightwards, 3 layers of up to 7); an arrow that passes a layer takes a place in it like a node. The message says when the other direction would fit. Keep node labels under 20 characters (14 when 5 or 6 layers are drawn rightwards).
- **The check measures the picture.** It lays the diagram out with the real fonts and stops when a label has no clear place (on or beside its own arrow, covering no box and no other label, nearer its own arrow than any other, and leaving its arrow to be seen), when two arrows would run along the same line, when an arrow would pass behind a box it does not belong to, or when a node's text does not fit its box. Drawn rightwards, a label has to fit in the gap between two boxes: with 5 or 6 layers that is one short word. For longer labels use `"direction": "down"`, fewer layers, or leave the label out and say it in the narration.

## 2. A row of cells that changes: `array`

Use it to show what a list, queue, stack or ordered map holds, and how one operation after another changes it:
a sort, a cache deciding what to drop, a queue filling and draining.

```json
{ "type": "array", "heading": "Least recently used at the front",
  "items": ["a", "b", "c", "d"], "capacity": 4, "ends": { "front": "least recent", "back": "most recent" },
  "beats": [
    { "say": "A lookup of b is a hit, so b moves to the back.", "mark": { "value": "b" },
      "cues": [ { "at": "moves to the back", "do": { "move": { "value": "b" }, "to": "back" } } ] },
    { "say": "A miss stores e, one more than the row may hold, so the front entry is dropped.", "do": { "push": "e" },
      "cues": [ { "at": "front entry", "do": { "pop": "front" } } ] } ] }
```

- **Fields.** `items`: the cells at the start, as short texts or numbers. `capacity`: how many the row may hold, drawn as empty slots. The row may go past it for a moment, as code that stores and then evicts does (the cell past the last slot shows it), but it must be back within it when the scene ends. `ends`: words over the `front` and `back` ends. `index: false` hides the indices under the cells.
- **A place in the row** is an index from 0, `"front"`, `"back"`, or `{ "value": "b" }` for the one cell that holds that text.
- **`do`** takes one operation, or a list carried out in order:

| Operation | Does |
|---|---|
| `{ "push": "d" }` | adds a cell at the back (`"at": "front"` for the front) |
| `{ "insert": "x", "at": 2 }` | adds a cell at that index |
| `{ "pop": "front" }`, `{ "remove": { "value": "b" } }` | takes the cell at that place out |
| `{ "move": 1, "to": "back" }` | takes the cell at a place and puts it at another: `to` is the index it has afterwards, and `{ "value": "c" }` puts it just before c |
| `{ "swap": [0, 3] }` | exchanges two cells |
| `{ "set": 1, "to": "z" }` | replaces what a cell holds |

- **`mark`**: a place, or a list of places, is ringed: the cells being compared. **`pointers`**: up to 3 names under cells, as in `{ "i": 0, "j": 3 }`. Both are about the row as it stands, so an operation or a new sentence clears them. Given in the same beat as a `do`, they are placed once its operations have finished, on the row as it then is.
- **The engine carries the operations out**, one after another, 0.7 s each: an operation in a cue waits for those still moving, and the check warns when one falls far behind its word. Give a run of operations a beat each, or enough words between them. What the row holds after each one is worked out, never typed, so the picture cannot disagree with itself. A pop from an empty row, an index past the end, a value that no cell or more than one cell holds, a move, swap or set that changes nothing, and a row still over its capacity at the end are errors that show the row at that point. To show that the code ran and nothing moved, leave out the `do` and `mark` the cell.
- **Limits.** 12 cells at once in a wide frame, 7 in a tall one (a row with a `capacity` may hold one more than that while it is over its capacity); a cell holds up to 14 characters, and fewer when the row is long: the check measures the texts and stops when one does not fit its cell, saying how many characters do. Without a `capacity` the row stays in the middle of the frame, so it slides over a little when it grows or shrinks. Write narration that says what the operation does, and let the picture show the result.

## 3. Messages over time: `sequence`

Use it when the point is who says what to whom, in what order: a protocol handshake, a request passing through
services, a cache standing between a caller and a slow loader.

```json
{ "type": "sequence", "heading": "Two calls for the same key",
  "actors": ["Caller", "TTLCache", "Loader"],
  "messages": [
    { "from": "Caller", "to": "TTLCache", "label": "get_or_load(key, load)" },
    { "from": "TTLCache", "to": "Loader", "label": "load()" },
    { "from": "Loader", "to": "TTLCache", "label": "value", "reply": true },
    { "from": "TTLCache", "to": "TTLCache", "label": "store, then evict" } ],
  "beats": [ { "say": "The first call is a miss, so the cache calls the loader.", "reveal": 2 },
             { "say": "It keeps the value.", "reveal": 4, "focus": 4 } ] }
```

- **Fields.** `actors`: 2 to 5 names (4 in a tall frame), left to right. `messages`: top to bottom, each `{ "from", "to", "label" }` by actor name; `"reply": true` draws it dashed; a message from an actor to itself is a step it takes alone, drawn as a loop beside its line.
- **What a beat can do.** `reveal`: how many messages are visible from now on (reveal them all: the check warns about any the beats leave out). `focus`: which message (1-based) is drawn in the accent colour, for its sentence; it must be one already revealed.
- **Limits.** 9 messages in a wide frame, 14 in a tall one; a message that names someone who is not an actor is an error.
- **The check measures the labels.** A label has two lines between its two parties (or beside its party, for a message to itself). One that does not fit is set smaller; one that still would be cut stops the check, which says about how many characters fit on a line there. A row is as tall as its label, so nine messages with two-line labels do not fit under a heading with a `sub`: the check says so. `focus` changes the colour of a message, never its size. A name that does not fit above its line is an error too.

## 4. A chart of the source's numbers: `chart`

Use it when the source holds a column of numbers and their shape is the point: a benchmark, a results table
that is too long to read as a table, a measurement over time.

```json
{ "type": "chart", "heading": "Hit rate by size", "file": "hit_rates.csv", "rows": [1, 8], "expect": "maxsize",
  "x": "maxsize", "y": "hit rate",
  "beats": [ { "say": "With room for only 4 entries, {value} of the lookups are hits.", "highlight": { "x": "4" } } ] }
```

- **The numbers come from a file, and only from a file.** `file` with `rows: [first, last]` for a `.csv` or `.tsv` (data rows, after the header), or with `lines: [first, last]` around a Markdown table or a LaTeX `tabular`, where `rows: [first, last]` may then pick some of the table's rows (counted from 1 under its header). `skip: [3, 7]` leaves rows out by number; the line under the heading says which. `ref` works as in a `table` scene. `expect` is text from the table's first line; for a CSV, text from the header or from the first row you show (give the latter when you point at rows by number, so that rows which have moved are caught). Blank lines of a CSV are not counted as rows. There is no way to type a value in, and the line under the heading is written for you, so a chart takes no `sub`. If the source gives its numbers only in prose, show them in a `table` or `stats` scene, written out and credited; if it already has a chart as a picture, show that with `image`.
- **Fields.** `x`: the column of names or positions. `y`: the column of numbers, or a list of columns (2 for bars, 3 for lines). `kind`: `"bar"` (the default) or `"line"`. `encoding` works as in a `table` scene.
- **What counts as a number.** The whole cell must be one number: digits, a decimal point, commas or thin spaces only between groups of three (`1,250`), a sign, a power of ten (`3e2`), `k` or `M` for thousands and millions (`1.2M`), and one unit at most: `%`, `×`, a currency sign, or a word of letters (`12.5 ms`, `40 req/s`). What a paper puts round a number is read through: `$91.2\%$`, `\textbf{93.1}`, `12\,345`. A cell that is anything else is refused with its row named: `1,25` and `0,750` (decimal commas), `1:45`, `1m30s`, `0x10`, `12*`, `2^10`, `71.2 ± 0.4`. A bar drawn from the first digits of such a cell would show another number. Leave that row out with `skip`, or show the column in a `table`. Empty cells (`-`, `n/a`, `NaN`) break a line and are refused in a bar.
- **Units.** A column whose cells carry different units is refused, and so are two columns whose cells do (`s` and `sec`, `$` and `USD` count as the same). A unit that stands only in a header's bracket, as in `time (ms)`, is a hint: when two headers seem to give different units the check warns and draws them, because `latency (min)` may be the minimum and not minutes. `{value}` is the cell as written, so it has no unit when the unit is only in the header: say the unit yourself.
- **Rows are called by their number in the file** (or in the table), in messages, in `skip` and in `highlight`: with `rows: [5, 10]` the first bar is row 5.
- **Bars** lie on their sides, one row of the file each, in the file's order, at most 12. Each bar carries its number exactly as the file writes it. Names beside the bars take two lines if they must; the check stops when one still would be cut.
- **Lines** take up to 400 rows. When every cell of the `x` column is a plain number in one unit, in rising order, the rows are placed by those numbers (`1k`, `2k`, `4k` are 1000, 2000, 4000) and the axis is marked in round numbers; otherwise they are spread evenly in the file's order and labelled as the file writes them. That holds for names, for dates and times however they are written (`2024-09`, `202409`, `9:30`, `0930`), for versions such as 2.10 after 2.9, and for sizes in mixed units. `"spacing": "even"` asks for even spacing; `"spacing": "numbers"` places even date-like digits as the numbers they are, and is an error when the column cannot be read as rising numbers. A line's y axis starts at zero only when the values come near zero; otherwise it starts just below the smallest, so say in the narration how large the difference is and do not let the slope say it.
- **What a beat can do.** `reveal`: how many of the `y` columns are drawn from now on. `highlight`: `{ "x": "4" }` (the row whose `x` cell is that text) or `{ "row": 3 }` (the row's number in the file); when the chart draws several columns, `"series": "column name"` is required, and the column must already be drawn. A list highlights several. On bars the rest dim; on a line the point gets a dot and its number. It lasts for its sentence.
- **Quote, do not retype.** In `say`, `{value}` stands for the highlighted cell as the file writes it and `{x}` for its row's name; when a sentence highlights several, give each `"as": "name"` and write `{name.value}`. Anything else in braces is an error. A number you type into a sentence is yours to get right, as in any scene: quote where you can.
- **What the check refuses.** A cell that is not a number (it is named, with the `skip` that leaves it out), a column whose cells mix units, two columns whose cells are in different units, numbers too large or too close together to mark on an axis, more rows than fit (12 bars: choose with `rows`), a name that does not fit beside its bar. It warns when the first line read looks like data and not like column names: a file with no header row would lose its first row. Bars are measured from zero, always: there is no setting to cut the axis.

## 5. Staying truthful with these

- A `diagram`, `array` or `sequence` is your reading of the source, so every node, operation and message must be something the source does. Show the code or the text it comes from in a scene beside it, and do not add a step to make the picture tidier.
- In a video with a source, a `diagram`, `array` or `sequence` about something the source does not say is marked `"beyond": true`, like any other scene (SKILL.md section 7).
- A `chart` shows the file and cannot be `beyond`. Say in the narration what was measured and how, as far as the source says; a chart with no account of where its numbers come from proves nothing.
