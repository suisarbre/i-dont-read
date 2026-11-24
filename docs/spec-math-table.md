# Spec: `math` and `table` scenes, inline `$...$`

Status: implemented · 2026-11-24

## Principle

The screen must tell apart **what the source says** and **what Claude wrote to explain it**,
exactly as `quote` (source) and `compare` (explainer) already do.

- Source mode: `file` + range. Shown as written, with `file:lines` in `sub`, pinned by `expect`.
- Explainer mode: content written in the storyboard. No `sub` line; explainer card style; optional `source` credit line.

## 1. `math` scene

```json
{ "type": "math", "heading": "Entropy", "file": "paper.tex", "lines": [42, 44], "expect": "H(X) =" }
{ "type": "math", "heading": "Chain rule",
  "tex": ["H(X,Y) = H(X) + H(Y \\mid X)", "\\le H(X) + H(Y)"] }
```

Source mode reads display math from `.tex` (`equation`, `align`, `\[...\]`, `$$...$$`) or `.md` (`$$...$$`)
inside the range. The LaTeX is never altered. A range with no math is an error that points to explainer mode.

Beats:
- `reveal`: number of lines shown from now on (step-by-step derivation).
- `mark`: `{ "line": 1, "tex": "H(Y \\mid X)" }` — a substring of that line's LaTeX. The engine wraps it in
  `\htmlClass{mark-N}{...}` before rendering. Not found, or not a balanced group → check error.
- `note`: short label beside the current mark.

Rules and limits:
- KaTeX is vendored in `idr/web/katex/` (JS, CSS, fonts, MIT license). No network at render time.
- `check` parses every expression with KaTeX and reports errors with scene and line.
- At most 4 lines. The block shrinks to fit above the captions; warn when it falls below a readable size.
- Narration with LaTeX-like characters (`$`, `^`, `\`, `_`, `{}`) and no `speak` → warning (TTS cannot read LaTeX).
  Plain-English narration about a formula needs no `speak`.

## 2. `table` scene

```json
{ "type": "table", "heading": "Calgary results", "file": "README.md", "lines": [30, 38], "expect": "| Program |" }
{ "type": "table", "file": "bench.csv", "rows": [1, 6], "columns": ["Program", "Size"] }
{ "type": "table", "heading": "Three codes for pi",
  "header": ["Code", "bits/digit"],
  "rows": [["BCD", "4.0"], ["Huffman", "3.4"], ["Shannon limit", "3.3219"]],
  "source": "DCE section 1.2" }
```

Source mode: a Markdown pipe table within `lines`, or a CSV with `rows` (data rows, 1-based) and optional
`columns` (pick and order by header name). Cell text is shown as written; Markdown marks are removed as in `quote`.
No computed values, no re-sorting.

Beats:
- `reveal`: data rows shown from now on (header always visible).
- `highlight`: `{ "row": 2 }`, `{ "col": "bits/digit" }`, `{ "cell": [3, "bits/digit"] }`; columns by name or 1-based
  index; `null` clears.
- `note`: short label beside the highlight.

Rules and limits:
- Columns whose cells are all numbers are right-aligned.
- Wide: at most 6 columns × 8 rows, 40 characters per cell. Tall: warn above 4 columns.
- Explainer `source` is shown as a credit line under the table.

## 3. Inline `$...$`

Rendered with KaTeX in: `quote` paragraphs, `table` cells, `compare` points, `flow` labels and descs,
`stats` labels and notes, `steps` titles and details, headings.

A dollar sign is not always math (prices, shell variables, regex), so delimiters follow the Pandoc rule:
- an opening `$` must be followed by a non-space character;
- a closing `$` must be preceded by a non-space character and **not** followed by a digit;
- `\$` is a literal dollar;
- nothing inside inline code (`` `...` ``) or fenced code is treated as math;
- `$$...$$` is display math (only meaningful in `quote`; elsewhere rendered inline-sized).

Examples: `costs $5 to $10` → no math (closing candidate is followed by `1`). `$HOME` alone → no closing `$`, no math.
`$\log_2 1/p$ bits` → math.

Fallback: if a span matches the rule but KaTeX fails to parse it, the raw text is shown unchanged and `check` warns.
In source mode this keeps the screen truthful: worst case the reader sees exactly the file's characters.

Opt-out: `"math": false` on any scene shows `$` literally.

`mark` in `quote` still matches screen text, but may not start or end inside a math span (check error).
Math terms inside quotes are not markable; use a `math` scene for that.

## 4. Files touched

| File | Change |
|---|---|
| `idr/plan.py` | `_math`, `_table` builders, inline-math tokenizer, `SCENES` entries, checks |
| `idr/source.py` | display-math extraction (`.tex`, `.md`), Markdown table and CSV parsers |
| `idr/web/player.js`, `theme.css` | `math` and `table` renderers; inline KaTeX in existing builders |
| `idr/web/katex/` | vendored KaTeX + license |
| `SKILL.md` §4, §8, §9 | scene table, truthfulness rules, limits |
| `examples/math-table/` | one storyboard using both scenes and inline math |

## 5. Tests

- Tokenizer table: prices, `$HOME`, `\$`, code spans, nested braces, `$$...$$`, adjacent spans.
- `mark` substring wrapping: found, missing, unbalanced.
- KaTeX parse failure → warning + raw fallback.
- Markdown table with alignment row, escaped pipes, inline code; CSV with quoted commas.
- Limits: 7 columns, 9 rows, 41-character cell, 5 math lines.
- Preview snapshots of both scenes in wide and tall.
