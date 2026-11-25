---
name: i-dont-read
description: Turn a codebase, a file or document, a commit or pull request, a web page, a PDF, pasted text or a plain topic into a short narrated explainer video (mp4) that shows the real source on screen with highlights, infographics, voice-over, sound effects and chapters, and answer follow-up questions about it the same way. Use when the user says "explain this as a video", "make a video about this repo / file / doc / PR / page", "I don't want to read this, show me".
---

# I don't read

The user does not want to read the thing. You read it, decide what matters, and hand back a video that explains it: one idea per chapter, the real source on screen, a voice talking over it.

You write a **storyboard** (a JSON file). The engine in `idr/` turns it into an mp4: it speaks every sentence with a local voice model, times the visuals to the audio, films each scene in headless Chrome, and mixes in sound effects.

## 1. The answer is a video, and only a video

The user asked not to read. So your reply is the mp4 and one caption line with its title and length, such as `How the cache works · 2:10`. Nothing else.

- No summary, no chapter list, no description of the scenes, no offers of what to do next. The chapters are already in the video.
- No outline to approve. Choose the chapters yourself and build. If the user wants something different after watching, they will say so, and unchanged scenes are reused.
- While you work, do not narrate. Send nothing until there is a video to send.
- **If you cannot make the video, the explanation is a video too** (section 2).
- If the video differs from what was asked in a way the user must know (English narration when they asked for another language, a file you could not read, a page that stops at a login or subscription wall), add one short sentence to the same caption line, in the user's language.
- Use plain text only when no video can exist at all: the engine could not be fetched, or this session cannot send files. Then write one line saying what is wrong.

**For the rest of the conversation.** Once the user has asked for a video, keep answering that way until they say otherwise.

- A question that asks for an explanation ("why is it done that way?", "what is marching squares?", "and how does it expire?") gets a video (section 7).
- A question that one or two lines of text answer in full gets those lines and no video: a fact to look up ("which file was that in?", "how long is it?"), a yes or no, a question about the video itself or about how you made it. A video takes minutes; do not spend them on a sentence. When you cannot tell which kind a question is, make the video.
- A request to change the video ("make scene 3 shorter", "use the dark theme") gets the new video and its caption line.
- A request to do something other than explain (write code, fix a bug, find a file) is done the normal way.
- The user can switch at any time. "Answer in text", "just tell me" or the like turns the videos off: from then on answer in plain text, as you would without this skill. Asking for a video again ("as a video", "show me") turns them back on.

This rule covers what the skill produces. Permission prompts and confirmations that the session itself requires are still asked the normal way.

## 2. Find the engine, and what to do when something is missing

The engine is the `idr/` folder next to this file. If it is not there (the skill was saved as this file alone), get it once per session:

```bash
git clone --depth 1 https://github.com/suisarbre/i-dont-read ~/i-dont-read
```

Call that folder `ENGINE` and run every command from it as `python -m idr ...`. Install what it needs, then check the machine:

```bash
pip install -r ENGINE/requirements.txt      # add --break-system-packages if pip asks for it
python -m idr doctor
```

`doctor` checks the Python packages, ffmpeg, the browser and the voice model. Try to fix what it reports yourself first (install the packages; `python -m playwright install chromium` for a browser). For anything you cannot fix:

| Situation | What you send |
|---|---|
| `doctor`, or a `blocked:` message from `render`, names a help video (`ENGINE/help/ffmpeg.mp4`, `chrome.mp4`, `packages.mp4`) | That video, as your whole reply. These are ready-made, so they work even when the engine cannot run. |
| The voice model cannot be downloaded | Render with `--silent` (captions carry the narration) and send the result together with `ENGINE/help/voice-model.mp4`. |
| `preview` or `render` warns that this machine has no font for some characters | Install a font that covers them if you can (Noto Sans CJK for Korean, Japanese and Chinese), then run again. Otherwise the user must install one: tell them with a `steps` video. |
| You need something from the user: a folder or file you cannot reach, a repository attached, a missing source, a choice only they can make | A short video you make now: one chapter with a `steps` scene that says what you need and how to give it to you. Use `--silent` if the voice is unavailable. |

## 3. Workflow

1. **Read the source yourself, properly.** For a codebase: the README, the entry points, and the handful of files that carry the design. For a document: all of it. For a web page: fetch it and read its text (section 5 has more on pages). If the user pasted text into the chat, save it to a file first (`work/source.md`), because scenes can only show text that is in a file. If there is no source (the user named a topic), or the user is asking a question about a video you already made, read section 7 first.
2. **Choose the chapters.** A chapter is one idea the viewer should walk away with. Explain one thing per chapter and cut; do not chain several ideas together. Most sources need 2 to 5 chapters. Let the content set the length: do not pad a small thing or cram a large one. With 3 or more chapters the video opens with a card that lists them, so the viewer sees the outline instead of reading one.
3. **Write `work/storyboard.json`** (format in section 4). `work` here is a scratch folder you make for this video, outside `ENGINE` and outside the source. Give its full path in every command, since the commands run from `ENGINE`.
4. **Check it:** `python -m idr check work/storyboard.json --root SOURCE_DIR`. It lists every scene (the opening card shows up as scene 1, "Overview") and every problem it can find in one run. A line that starts with `note:` is not a fault: it says how the engine read something that could be read two ways, and how to say otherwise; act on it only when it read it wrongly. Fix every error, and every warning you can (one about something on a web page that cannot be closed or framed out may have to stay). A field the engine does not know, in a beat, a cue, or a graph, is an error that names the nearest field it does know: nothing you write is dropped in silence. The lengths it lists are real for every sentence the voice has already spoken on this machine and estimates for the rest, usually within 5% overall. When the user asked for a length, run `check --spoken` before you trim or pad: it speaks every sentence now (about half the video's length, once; `render` reuses the clips) and lists the real lengths.
5. **Look at it before filming:** `python -m idr preview work/storyboard.json --root SOURCE_DIR --out work/out --beats`, then open the contact sheets it lists. `--beats` draws a frame for every change on screen (each beat and cue), so you see each highlight, note, box and camera position, not only how a scene ends. Each frame is taken at the end of its beat or cue, just before the next change: the finished picture, under the caption of the sentence that made it. Anything that takes time (a travelling point, a sweep, a growing area) also gets a frame half-way through. Without `--beats` you get one frame per scene; `--scenes 3,7-9` limits either to some scenes: it writes sheets named `..._preview_part_N.png` and redraws only those scenes' frames, so the sheets and frames of the last full preview stay as they were. The full-size frames are in `work/out/.work/preview/<storyboard name>/`. Fix anything cramped, clipped, wrapped badly, covered, or pointing at the wrong thing.
6. **Render once:** `python -m idr render work/storyboard.json --root SOURCE_DIR --out work/out`. A render keeps the user waiting, so do not render to "see how it looks"; that is what `preview` is for. It takes about as long as the video itself, more on a slow machine: if your tools stop a command after a few minutes, run it in the background and wait for it.
7. **Send the mp4** with its one-line caption. The render prints the length.

To change a finished video, edit the storyboard and render again. Scenes that did not change are reused and sentences that did not change are not re-spoken.

`--root` is the folder that `file` paths in the storyboard are relative to: the root of the repo or the folder holding the document. A `file` outside that folder (through `..`, an absolute path, or a link that points out of it) is an error: a scene shows files of the source. When every scene shows a web address, or the video has no source (`"source": "none"`), any folder will do (use `work`).

## 4. Storyboard format

```json
{
  "title": "How the cache works",
  "intro": { "say": "Three short chapters on why this server is fast." },
  "chapters": [
    {
      "title": "The fast path",
      "say": "Why do most requests never touch the database?",
      "scenes": [
        {
          "type": "code",
          "heading": "Check the cache first",
          "file": "server/handler.py",
          "lines": [38, 47],
          "expect": "def handle(request):",
          "beats": [
            { "say": "Every request enters through this one function.", "highlight": 38 },
            { "say": "Before anything else, it looks for a cached copy.", "highlight": [41, 43], "note": "cache first" }
          ]
        }
      ]
    }
  ]
}
```

`title` is required. `intro.say` is the one sentence spoken over the opening card; with 3 or more chapters that card lists the chapters (give it an `intro.say` too, or it plays silent), with fewer it appears only if you give `intro`. Other optional top-level fields: `theme` (`light` or `dark`), `voice`, `speed`, `captions`, `pronounce` (section 8), and `"source": "none"` when there is no source (section 7).

Each chapter opens with a title card that shows `title` and speaks `say`. Then its scenes play in order.

A **beat** is one spoken sentence plus what changes on screen when that sentence starts. A beat with nothing but `say` leaves the picture as it is. Every scene has a `heading`, a `sub` line under it, and a list of `beats`. On `code`, `diff` and `quote` scenes, and on `math` and `table` scenes read from a file, the engine writes `sub` itself (the file and the lines on screen); on the others it is yours and optional.

| Scene | Use it when | Fields | What a beat can do |
|---|---|---|---|
| `code` | The point is in specific lines | `file`, `lines: [first, last]`, `expect`, optional `ref` (show the file as it was at a git ref). With `"example": true` the file is one you wrote for the video (section 7) | `highlight`: a line number or `[first, last]` (stays until changed; `null` clears). `note`: a short label at the right end of the highlighted lines. It goes when the highlight moves on. When the code there runs to the right edge there is no room for it, and the check warns: shorten the note or drop it |
| `diff` | The point is what changed: a commit, a PR, a before and after | `file`, `from` (a git ref), optional `to` (a git ref; default is the file on disk), `lines: [first, last]` in the new file, `expect`. Or `before` and `after`: two file paths | `show`: `"removed"`, `"added"` or `"changed"` lights those lines. `highlight` and `note` as in `code`, by new-file line number |
| `quote` | The source says it best in its own words: prose in a text or Markdown file | `file`, `lines: [first, last]`, optional `ref`. Consecutive lines are joined into paragraphs (a blank line or a list item starts a new one) and Markdown marks are removed, so do not use it for code or for comments inside code | `mark`: a phrase, or a list of phrases, to run a marker over. Copy it as it reads on screen or from the raw Markdown, from within one paragraph |
| `image` | The source is a picture, a web page or a PDF | `file` (an image, or a PDF with `page`), or `url` (a web address or a local `.html` file). For a page, optional `click` and `top` (see "Web pages" below) | `zoom`: move the camera to a region (`null` goes back to the top of the picture at full width). `box`: outline a region and dim the rest (`null` removes it). A region is `{ "find": "exact words on the page" }` for web pages and PDFs, or `[x, y, width, height]` as fractions of the whole picture, from 0 to 1 |
| `flow` | A process or pipeline that runs in one line (for branches and loops, `diagram`) | `nodes: [{ "label", "desc" }]` (2 to 6) | `reveal`: how many nodes are visible from now on. `focus`: which node (1-based) gets the ring |
| `compare` | Two options, or before and after | `columns: [{ "title", "points": [] }, { ... }]` (exactly 2, up to 5 rows) | `reveal`: how many rows are visible from now on (a row is the same line in both columns) |
| `stats` | The numbers are the story | `items: [{ "value", "label", "note" }]` (1 to 4) | `reveal`: how many cards are visible from now on |
| `steps` | An ordered list: how to do something, or what you need from the user | `items: [{ "title", "detail", "cmd" }]` (1 to 6; `cmd` shows a command in monospace) | `reveal`: how many steps are visible from now on |
| `math` | A formula is the point: from the source, or one you write to explain it | Read `ENGINE/guides/math.md` before you write one | Reveal formulas one by one, mark a term, put a note by it |
| `table` | Rows and columns: results, options, a comparison of several things | From the source: `file` with `lines: [first, last]` around a Markdown table or around one LaTeX `tabular` in a `.tex` file (from its `\begin` line to its `\end` line), or a `.csv`/`.tsv` with `rows: [first, last]` (data rows after the header) and optional `columns` (names or 1-based numbers, in the order to show). Written for the video: `header` and `rows`, plus `source` for a credit line | `reveal`: how many rows are visible (the header always is). `highlight`: `{ "row": n }`, `{ "col": name or n }` or `{ "cell": [n, col] }` (`null` clears). `note`: a short label on the highlight's outline. A highlight dims every other cell, the header included (a highlighted column keeps its own header), and stays until the next `highlight`; a `note` goes when the next sentence starts |
| `plot` | The source is about mathematics, and the shape of a curve is the point | Read `ENGINE/guides/math.md` before you write one | Draw curves, and put points, tangents, areas, sums and arrows on them; every number is worked out by the engine |
| `diagram` | Parts that branch, loop or depend on each other: a state machine, a decision, modules | Read `ENGINE/guides/diagrams.md` before you write one | Reveal nodes, ring one, walk along arrows; the engine lays it out |
| `array` | What a list, queue, stack or ordered map holds, and how operations change it | Read `ENGINE/guides/diagrams.md` before you write one | Push, pop, move, swap; the engine works out what the row holds after each |
| `sequence` | Who says what to whom, in order: a protocol, a request through services | Read `ENGINE/guides/diagrams.md` before you write one | Reveal messages one by one, pick one out |
| `chart` | The source has a file or table of numbers, and their shape is the point | Read `ENGINE/guides/diagrams.md` before you write one | Bars or lines drawn from the file's own numbers; nothing can be typed in |

**Three parts of these instructions are in files of their own**, so that a video carries only what it uses. They are not optional reading: what they cover cannot be done from this file alone.

| Read | When |
|---|---|
| `ENGINE/guides/math.md` | The source or the topic is mathematics: a formula to show, a paper with equations, a curve, a slope, an area. Read it before you write the storyboard. It has the `math` and `plot` scenes |
| `ENGINE/guides/diagrams.md` | You want to draw how something is put together or how it runs (a diagram with branches, a row of cells that changes, messages between parties), or the source has a file of numbers worth charting. It has the `diagram`, `array`, `sequence` and `chart` scenes |
| `ENGINE/guides/voice.md` | A sentence of narration holds anything that is not plain words (notation, a symbol, an identifier, a file name, an unusual name), or `check` warns that the voice cannot say something |

Any beat can also carry `speak` (see section 8) or, with no `say`, a `hold` in seconds. `intro` and a chapter take `speak` beside their `say` too.

**Math in any text.** `$...$` in headings, `quote` text, `table` cells, `flow`, `compare`, `stats` and `steps` text, `diagram` labels, `array` cells and `sequence` message labels is typeset as math, while `$5 to $10` and `$HOME` stay plain text. The rule, and how to turn it off, is in `ENGINE/guides/math.md`.

In scenes with `reveal`, show the first item when the first sentence starts: a scene that stays empty while the voice talks looks broken, and the check warns about it. A scene with no `reveal` at all shows everything from the start.

**Regions in an `image` scene.** `find` puts the box on the words themselves, one outline per line they run over. If the words occur more than once, the first place a reader can see wins, so make the phrase long enough to be the one you mean. A `box` does not move the camera: put `zoom` to the same region on the same beat, or the box may be out of frame (the check warns). The camera chooses how close to go: on a web page a `find` zoom holds the whole width of the paragraph the words are in, and a region taller than the frame is shown whole with the picture pulled back. To frame something wider or tighter, give the `zoom` as fractions instead.

Source files are read as UTF-8. For a file in another encoding, add `"encoding"` to its `code`, `diff` or `quote` scene, for example `"encoding": "cp949"`. Never guess: a wrong encoding puts text on screen that is not in the file.

**Timing inside a sentence.** By default a beat's action fires when its sentence starts. To fire it on a word instead, add `"at": "a word or phrase from say"` (it is looked up in `say`, also when the beat has `speak`; the first place it occurs is used, capitals aside, so pick plain words with no `{...}` in them). Everything on the beat moves to that word; to start one thing with the sentence and another on a word, put the second in a cue. To do several things during one sentence, add `cues`, each with its own `at`:

```json
{ "say": "It builds a key, looks in the cache, and returns early on a hit.",
  "at": "builds a key", "highlight": 3,
  "cues": [ { "at": "looks in the cache", "highlight": 4 },
            { "at": "returns early", "highlight": [5, 6], "note": "fast path" } ] }
```

Use this when one sentence walks across several lines or items. It reads far better than three short sentences, and the voice model reports when each word is spoken, so the picture lands on the word.

A chapter is usually 1 to 3 scenes. Alternate real source (`code`, `diff`, `quote`, `image`, and `math` or `table` read from a file) with an infographic (`flow`, `compare`, `stats`, `plot`, and `math` or `table` written for the video) that puts it in context.


## 5. Web pages

An `image` scene with `url` photographs the page in a real browser: 1440 px wide, and up to 3600 px tall, from the top. Before the picture is taken the page is scrolled through once, the way a reader would, so parts that load only when they come into view are there. Nothing is removed from the page and nothing is added to it.

- **Read the page first.** Fetch it and read the text, so you know what it says and can copy `find` phrases exactly. A phrase may run across bold, links and line breaks, but not from one paragraph into the next.
- **Longer pages.** To show a part further down, add `"top": "words where that part starts"`: the capture begins just above those words. Use one scene per part of a long page. The check tells you when a `find` is below what was captured.
- **Consent dialogs and banners.** If something fixed covers the page, the check says so, quotes it, and lists the buttons on it. Close it the way a reader would, with `"click": ["Reject non-essential"]` (the exact words on a button, link or tab; several are pressed in order). Prefer the button that declines. `click` also opens a tab or a "show more". Give the same `click` on every scene of that page.
- **Pictures that did not load, and boxes that float over the page** (a newsletter prompt, a chat bubble) are reported too. Frame them out with `zoom`, or close them with `click`.
- **Login and subscription walls.** Explain only what the page shows. Show the wall itself in a scene, say on screen that the page stops there, and add a sentence to the caption. Do not fill in the hidden part from what you know about the topic.
- **A page you cannot open at all** (it needs a login, or the network blocks it) is "something you need from the user" (section 2): say which page, and that a saved copy (`.html` or PDF) would work.
- If the built-in capture cannot show the page properly even with `click` and `top`, you may take the screenshot yourself in the same honest way (press only what a reader would press, edit nothing), show it with `file`, and say in `sub` what you did. You lose `find`, so check every box by eye in the preview.
- A page is photographed once an hour at most; delete `~/.cache/i-dont-read/pictures` to force a fresh picture. A saved `.html` file is photographed every time.

Do not point a `quote` scene at an `.html` file: it would show the markup.

## 6. Explaining a change (a commit, a pull request, a diff)

When the user points at a change instead of a codebase, the video answers four things: what the change is, in one sentence; how it worked before, or what was wrong; what was changed; and what happens now.

**Read first.** Make sure both ends of the change exist locally (fetch the base and the head). Then:

```bash
git log --format='%h %s%n%b' BASE..HEAD     # what the author said they did, and why
git diff --stat BASE..HEAD                  # how big it is, and where
git diff BASE..HEAD                         # the change itself
```

Read the pull request description and any linked issue too, if you can reach them. Read enough of the surrounding code to know what the changed lines do.

**Sort the change into intents, not files.** One chapter per intent. A pull request that fixes a bug and also renames a module has two intents; a fix that touches four files has one. Renames, formatting and other mechanical edits get one sentence, or nothing.

**Each chapter answers its questions in order**, by the kind of change:

| Kind | The chapter answers, in this order |
|---|---|
| Bug fix | What went wrong, as someone using it saw it → where the old code caused it → what was changed → what happens now |
| New feature | What can be done now that could not be before → where it plugs into the existing code → the new code that matters most → what it does not do yet |
| Refactor | What behaves exactly as before → what moved or was reshaped → why, if the author says |
| Removal | What is gone → what replaces it, or what stops working without it |

The first spoken sentence of the video (`intro.say`, or the first chapter's `say`) says what the whole change is, in plain words.

**Where the "why" comes from.** A diff shows what changed, never why. Take the reason only from what the author wrote: commit messages, the pull request description, a linked issue, code comments, tests. If none of them gives a reason, describe what changed and what it does, and leave the motive out. Do not infer a bug that nobody reported.

How the old code behaved is a claim as well. Say it only when you can point at it: the old lines, a test that changed, or a run of both versions (running them is welcome, in a scratch copy outside the repository).

**Keep it in proportion.** The four questions are an order, not four scenes. A one-line fix is one `diff` scene whose beats walk through them, plus at most one more scene. Several small fixes on one branch get a chapter each, of one or two scenes.

**Showing before and after.**

- A `diff` scene with `from` set to BASE and `to` set to HEAD is the main scene. Use `"show": "removed"` while describing the old behaviour and `"show": "added"` for the new. `show` lights those lines until another `show` replaces it, and a `highlight` and `note` can sit on top of it. Removed lines take room: the 16-line limit counts every line on screen, the removed ones included.
- To show old code that the diff does not carry (unchanged context, or a function before it was rewritten), use a `code` scene with `"ref": "BASE"`. Its subtitle says which version is on screen.
- For the size of the change, use a `stats` scene with the numbers from `git diff --stat`, and name that command in `note`. It belongs at the start (the first chapter), before the intents, not under the last one.
- A `compare` scene (before and after) suits a change in behaviour that is easier to say than to show.

## 7. No source, follow-up questions, and going past the source

Sometimes there is no source to stand on, or not enough of one:

- **A topic alone**: "explain Taylor series", "how does TLS work".
- **A follow-up question** about a video you made: "why is it done that way?", "what is marching squares?".
- **A question the source does not answer**, whatever the user pointed at.

**A topic with nothing to look up** ("explain the chain rule", "how does binary search work"): settled mathematics or a standard algorithm that you can derive or run yourself needs no fetched page. Put `"source": "none"` and explain it with `math`, `plot`, `flow` and an example of your own.

**Otherwise look for a source first**, in this order: the source you already have (read more of it; the answer is often in a file you skipped); then a source you can fetch and show (the project's documentation, the paper, the standard, the official page: an `image` scene with its `url`, or a saved copy in a `quote` scene); then what you know. Only the last is "past the source".

**The screen says which is which.** The viewer must be able to tell the source from your explanation, so the engine labels it and the check enforces it:

- **No source at all:** put `"source": "none"` at the top of the storyboard. The opening card then says the video is explained from general knowledge, with no source document. The check demands this when no scene shows a source, and refuses it when one does. (A video of nothing but `steps`, such as a request to the user, needs neither.)
- **Some scenes go past the source:** put `"beyond": true` on each such scene, or on the chapter when all of it does. Their header carries a "beyond the source" label. A scene that shows the source cannot be marked. A scene that sums up the source (a `flow` of its pipeline, `stats` from its numbers) is not beyond it and gets no mark.
- **What you explain with:** `math` with `tex`, `plot`, `flow`, `compare`, `steps`, `stats`, and `table` with `header`.
- **Code of your own:** write it to a file beside the storyboard (`work/example.py`), never into the source folder, and show it with a `code` scene that has `"example": true`. Its `file` is relative to the storyboard's folder, its subtitle says "Example written for this video" instead of naming a file, and it is labelled beyond the source. Run the example first if it can run, and say only what you saw it do.
- Never put your own prose in a `quote` scene, or your own picture in an `image` scene. Your words are the narration.

**What you may say past the source.**

- Only what is settled and you are sure of: definitions, mathematics you can derive, how a standard algorithm or protocol works.
- Anything that changes (versions, prices, who holds a role, what an API does today, benchmark results) must be looked up, and then the page you found is a source: show it.
- No number without an origin. In `stats`, `table` and `compare`, say where each figure is from in `note` or `source`. Let `plot` work out coordinates, slopes and areas, and let a run of your example produce its output.
- Do not put your explanation in the source's mouth: no "the author chose this because" unless the author wrote it. Say once, aloud, when you step past the source: "The file does not say why. In general, ...".
- If you are not sure, say that it is not known, or leave it out.

**A follow-up question** that asks for an explanation is answered with another video (section 1 says which questions get a line of text instead): usually one or two chapters, 30 to 90 seconds.

- Write a new storyboard (`work/followup-1.json`) and render it with the same `--root`. Keep the first storyboard; the user may ask about it again.
- Start where the question points: show that place in the source again (the same `code` or `quote` lines, or tighter), then answer. Do not recap the first video.
- If the source answers the question, this is an ordinary video. If it does not, show what the source does say, then go past it in scenes marked `beyond`.
- If the follow-up is to a video that had no source, the new one has `"source": "none"` too.

## 8. Writing the narration

- One sentence per beat, about 25 words at most. Write it to be heard, not read.
- Say what the highlighted thing does and why it matters. Never read code aloud.
- The picture must match the words: put the `highlight`, `mark` or `reveal` on the beat whose sentence is about it.
- Say a formula in words ("H of X given Y", "the sum over n of x to the n"). Never put LaTeX or code in `say`.
- The voice reads short notation (`x^2`, `f(x)`, `n-th`) and many names correctly by itself, and gets identifiers, paths and made-up names wrong unless you add `speak` with how to say them: `"say": "It calls parse_args() first."`, `"speak": "It calls parse args first."` Whenever a sentence holds anything but plain words, or `check` warns that the voice cannot say something, read `ENGINE/guides/voice.md`: what is read for you, `speak`, a `pronounce` table for a name that keeps coming up, and how to see what the voice will say.
- A chapter's `say` is a hook: the question the chapter answers, or its promise in one line.
- Start with the content. No "in this video" and no "let's dive in". End the last chapter on the takeaway.
- Narration is English only for now. If the user asked for another language, or wrote to you in one, make the video in English and say so in the caption, in their language. Everything you write for the screen (title, chapter titles, headings, labels) is English too, so it matches the voice; the source appears in whatever language it is written in.

## 9. Stay truthful

This is the reason the skill exists, so do not work around it.

- `code`, `diff` and `quote` scenes show only what is in the file at those lines. Never paste code or prose into the storyboard.
- The same holds for `math` and `table` scenes with `file`: the LaTeX and the cells are shown as the file has them. (What changes is what LaTeX itself would change: `\label{...}` is dropped, an equation gets the number the paper prints, and in a LaTeX table `$-0.8$` is shown as the number −0.8 and `\textbf{...}` as its text.) If the source writes a formula as plain text, like `log2 1/p`, do not present your LaTeX version of it as the source: write it in a `math` scene with `tex`, which is shown as an explanation, with no file line.
- A `math` or `table` scene with `tex` or `header` is your explanation. Every value in a written table must come from the source, as in `stats`; name where in `source`.
- Whatever is not from the source is labelled on screen: `"source": "none"` for a video with no source, `"beyond": true` for scenes that go past one, `"example": true` for code you wrote (section 7). Do not leave the label off to make a video look better sourced than it is.
- A `chart` scene draws numbers from a file of the source, read by the engine; a number cannot be typed into it. It shows the source, like a `table` scene with `file`.
- A `plot` scene is your explanation too. Plot a function the source gives or is plainly about, and say where it is from in `source`. Its points, slopes and areas are worked out by the engine from the formula, so they are exact for what is drawn; they are not a claim the source made unless the source says so.
- Always set `expect` on a `code` or `diff` scene to a short string from the **first line** of `lines`. It pins the range: the render stops if that line is no longer there. Start the range on a line with something of its own on it, not on a lone brace.
- A `mark` must be copied exactly from the quoted lines, and a `find` exactly from the page. The render stops if either is not found.
- An `image` scene shows the real file or the real page. Do not draw or generate a picture and present it as the source.
- Every number in a `stats` scene and every claim in a `compare` scene must come from the source (or, in a scene marked as past the source, from something you can name: section 7). Put where it came from in `note` when you can. A number you worked out from the source's own numbers is fine when `note` shows what it was worked out from.
- If the source does not say something, the video does not say it either, except in scenes marked as going past the source, under the rules of section 7.

## 10. Limits the check enforces

- `code` and `diff`: at most 16 lines on screen per scene (on a diff, removed lines count), and 12 or fewer reads best. In the wide format the font shrinks to fit the longest line, so lines over about 120 columns (114 on a diff) make the code too small, and the tall format wraps long lines instead. Pick the lines that matter and split long passages into two scenes.
- `quote`: at most 640 characters. Quote the paragraph that matters, not the page.
- `flow` labels: about 12 characters with 5 or 6 nodes, 18 with fewer. Keep `desc` to a few words.
- `compare` points: at most 80 characters. A `note` beside a highlight: two or three words.
- `stats` values: at most 10 characters. Put the words in `label`.
- `steps`: titles and commands at most 48 characters each.
- `math` and `plot`: their limits are in `ENGINE/guides/math.md`. `diagram`, `array`, `sequence` and `chart`: in `ENGINE/guides/diagrams.md`.
- `table`: at most 6 columns and 8 rows (4 columns read best in the tall format), and 40 characters per cell.
- Headings: at most 60 characters.

## 11. Settings

- Theme: light by default. If the user asks for dark, add `--theme dark` (or `"theme": "dark"` in the storyboard).
- Format: wide (1920×1080) by default. If the user wants a vertical video, for a phone or for Shorts, add `--format tall` (1080×1920). The same storyboard works in both; preview it again in the format you will render.
- A `.i-dont-read.json` file in `--root` sets the user's defaults: `{ "theme": "dark", "format": "tall", "voice": "am_michael", "speed": 1.0, "captions": true }`. If the user wants a setting to stick, write it there. It can also hold `"pronounce"` (section 8).
- `python -m idr voices` lists the voices (the default is `af_heart`). `--voice NAME` picks one, `--no-captions` turns the burnt-in captions off, `--silent` renders without voice.
- Output is 30 fps, named `<storyboard>_<theme>.mp4` in `--out` (`<storyboard>_<theme>_tall.mp4` for the tall format).
