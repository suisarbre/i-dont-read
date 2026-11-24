---
name: i-dont-read
description: Turn a codebase, a file or document, a commit or pull request, a web page, a PDF or pasted text into a short narrated explainer video (mp4) that shows the real source on screen with highlights, infographics, voice-over, sound effects and chapters. Use when the user says "explain this as a video", "make a video about this repo / file / doc / PR / page", "I don't want to read this, show me".
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

1. **Read the source yourself, properly.** For a codebase: the README, the entry points, and the handful of files that carry the design. For a document: all of it. For a web page: fetch it and read its text (section 5 has more on pages). If the user pasted text into the chat, save it to a file first (`work/source.md`), because scenes can only show text that is in a file.
2. **Choose the chapters.** A chapter is one idea the viewer should walk away with. Explain one thing per chapter and cut; do not chain several ideas together. Most sources need 2 to 5 chapters. Let the content set the length: do not pad a small thing or cram a large one. With 3 or more chapters the video opens with a card that lists them, so the viewer sees the outline instead of reading one.
3. **Write `work/storyboard.json`** (format in section 4).
4. **Check it:** `python -m idr check work/storyboard.json --root SOURCE_DIR`. It lists every scene (the opening card shows up as scene 1, "Overview") and every problem it can find in one run. Fix every error, and every warning you can (one about something on a web page that cannot be closed or framed out may have to stay).
5. **Look at it before filming:** `python -m idr preview work/storyboard.json --root SOURCE_DIR --out work/out --beats`, then open the contact sheets it lists. `--beats` draws a frame for every change on screen (each beat and cue), so you see each highlight, note, box and camera position, not only how a scene ends. Without it you get one frame per scene; `--scenes 3,7-9` limits either to some scenes. The full-size frames are in `work/out/.work/preview/`. Fix anything cramped, clipped, wrapped badly, covered, or pointing at the wrong thing.
6. **Render once:** `python -m idr render work/storyboard.json --root SOURCE_DIR --out work/out`. A render keeps the user waiting, so do not render to "see how it looks"; that is what `preview` is for. It takes about as long as the video itself, more on a slow machine: if your tools stop a command after a few minutes, run it in the background and wait for it.
7. **Send the mp4** with its one-line caption. The render prints the length.

To change a finished video, edit the storyboard and render again. Scenes that did not change are reused and sentences that did not change are not re-spoken.

`--root` is the folder that `file` paths in the storyboard are relative to: the root of the repo or the folder holding the document. When every scene shows a web address, any folder will do (use `work`).

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

`title` is required. `intro.say` is the one sentence spoken over the opening card; with 3 or more chapters that card lists the chapters (give it an `intro.say` too, or it plays silent), with fewer it appears only if you give `intro`. Other optional top-level fields: `theme` (`light` or `dark`), `voice`, `speed`, `captions`.

Each chapter opens with a title card that shows `title` and speaks `say`. Then its scenes play in order.

A **beat** is one spoken sentence plus what changes on screen when that sentence starts. A beat with nothing but `say` leaves the picture as it is. Every scene has a `heading`, a `sub` line under it, and a list of `beats`. On `code`, `diff` and `quote` scenes the engine writes `sub` itself (the file and the lines on screen); on the others it is yours and optional.

| Scene | Use it when | Fields | What a beat can do |
|---|---|---|---|
| `code` | The point is in specific lines | `file`, `lines: [first, last]`, `expect`, optional `ref` (show the file as it was at a git ref) | `highlight`: a line number or `[first, last]` (stays until changed; `null` clears). `note`: a short label beside the highlight |
| `diff` | The point is what changed: a commit, a PR, a before and after | `file`, `from` (a git ref), optional `to` (a git ref; default is the file on disk), `lines: [first, last]` in the new file, `expect`. Or `before` and `after`: two file paths | `show`: `"removed"`, `"added"` or `"changed"` lights those lines. `highlight` and `note` as in `code`, by new-file line number |
| `quote` | The source says it best in its own words: prose in a text or Markdown file | `file`, `lines: [first, last]`, optional `ref`. Consecutive lines are joined into paragraphs (a blank line or a list item starts a new one) and Markdown marks are removed, so do not use it for code or for comments inside code | `mark`: a phrase, or a list of phrases, to run a marker over. Copy it as it reads on screen or from the raw Markdown, from within one paragraph |
| `image` | The source is a picture, a web page or a PDF | `file` (an image, or a PDF with `page`), or `url` (a web address or a local `.html` file). For a page, optional `click` and `top` (see "Web pages" below) | `zoom`: move the camera to a region (`null` goes back to the top of the picture at full width). `box`: outline a region and dim the rest (`null` removes it). A region is `{ "find": "exact words on the page" }` for web pages and PDFs, or `[x, y, width, height]` as fractions of the whole picture, from 0 to 1 |
| `flow` | A process, pipeline or sequence of parts | `nodes: [{ "label", "desc" }]` (2 to 6) | `reveal`: how many nodes are visible from now on. `focus`: which node (1-based) gets the ring |
| `compare` | Two options, or before and after | `columns: [{ "title", "points": [] }, { ... }]` (exactly 2, up to 5 rows) | `reveal`: how many rows are visible from now on (a row is the same line in both columns) |
| `stats` | The numbers are the story | `items: [{ "value", "label", "note" }]` (1 to 4) | `reveal`: how many cards are visible from now on |
| `steps` | An ordered list: how to do something, or what you need from the user | `items: [{ "title", "detail", "cmd" }]` (1 to 6; `cmd` shows a command in monospace) | `reveal`: how many steps are visible from now on |

Any beat can also carry `speak` (see section 7) or, with no `say`, a `hold` in seconds. `intro` and a chapter take `speak` beside their `say` too.

In scenes with `reveal`, show the first item when the first sentence starts: a scene that stays empty while the voice talks looks broken, and the check warns about it.

**Regions in an `image` scene.** `find` puts the box on the words themselves, one outline per line they run over. If the words occur more than once, the first place a reader can see wins, so make the phrase long enough to be the one you mean. A `box` does not move the camera: put `zoom` to the same region on the same beat, or the box may be out of frame (the check warns). The camera chooses how close to go: on a web page a `find` zoom holds the whole width of the paragraph the words are in, and a region taller than the frame is shown whole with the picture pulled back. To frame something wider or tighter, give the `zoom` as fractions instead.

Source files are read as UTF-8. For a file in another encoding, add `"encoding"` to its `code`, `diff` or `quote` scene, for example `"encoding": "cp949"`. Never guess: a wrong encoding puts text on screen that is not in the file.

**Timing inside a sentence.** By default a beat's action fires when its sentence starts. To fire it on a word instead, add `"at": "a word or phrase from say"` (it is looked up in `say`, also when the beat has `speak`). Everything on the beat moves to that word; to start one thing with the sentence and another on a word, put the second in a cue. To do several things during one sentence, add `cues`, each with its own `at`:

```json
{ "say": "It builds a key, looks in the cache, and returns early on a hit.",
  "at": "builds a key", "highlight": 3,
  "cues": [ { "at": "looks in the cache", "highlight": 4 },
            { "at": "returns early", "highlight": [5, 6], "note": "fast path" } ] }
```

Use this when one sentence walks across several lines or items. It reads far better than three short sentences, and the voice model reports when each word is spoken, so the picture lands on the word.

A chapter is usually 1 to 3 scenes. Alternate real source (`code`, `diff`, `quote`, `image`) with an infographic (`flow`, `compare`, `stats`) that puts it in context.


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

## 7. Writing the narration

- One sentence per beat, about 25 words at most. Write it to be heard, not read.
- Say what the highlighted thing does and why it matters. Never read code aloud.
- The picture must match the words: put the `highlight`, `mark` or `reveal` on the beat whose sentence is about it.
- The voice mispronounces identifiers, paths and symbols. When a sentence needs one, keep `say` as it should appear in the caption and add `speak` with how to pronounce it: `"say": "It calls parse_args() first."`, `"speak": "It calls parse args first."`
- Acronyms in capitals are spelled out letter by letter (HTTP, URL, API, TLS), and numbers are read as numbers, so those need no `speak`. Made-up and mixed-case names often go wrong. You cannot listen, but you can look: `python -m idr sounds "PyPI" "memtable"` prints how each will be pronounced (here "pie pie" and "mem-tuh-bul"), and you can try a respelling the same way (`"pie pee eye"`, `"mem table"`) before putting it in `speak`.
- A chapter's `say` is a hook: the question the chapter answers, or its promise in one line.
- Start with the content. No "in this video" and no "let's dive in". End the last chapter on the takeaway.
- Narration is English only for now. If the user asked for another language, or wrote to you in one, make the video in English and say so in the caption, in their language. Everything you write for the screen (title, chapter titles, headings, labels) is English too, so it matches the voice; the source appears in whatever language it is written in.

## 8. Stay truthful

This is the reason the skill exists, so do not work around it.

- `code`, `diff` and `quote` scenes show only what is in the file at those lines. Never paste code or prose into the storyboard.
- Always set `expect` on a `code` or `diff` scene to a short string from the **first line** of `lines`. It pins the range: the render stops if that line is no longer there. Start the range on a line with something of its own on it, not on a lone brace.
- A `mark` must be copied exactly from the quoted lines, and a `find` exactly from the page. The render stops if either is not found.
- An `image` scene shows the real file or the real page. Do not draw or generate a picture and present it as the source.
- Every number in a `stats` scene and every claim in a `compare` scene must come from the source. Put where it came from in `note` when you can. A number you worked out from the source's own numbers is fine when `note` shows what it was worked out from.
- If the source does not say something, the video does not say it either.

## 9. Limits the check enforces

- `code` and `diff`: at most 16 lines on screen per scene (on a diff, removed lines count), and 12 or fewer reads best. In the wide format the font shrinks to fit the longest line, so lines over about 120 columns (114 on a diff) make the code too small, and the tall format wraps long lines instead. Pick the lines that matter and split long passages into two scenes.
- `quote`: at most 640 characters. Quote the paragraph that matters, not the page.
- `flow` labels: about 12 characters with 5 or 6 nodes, 18 with fewer. Keep `desc` to a few words.
- `compare` points: at most 80 characters. A `note` beside a highlight: two or three words.
- `stats` values: at most 10 characters. Put the words in `label`.
- `steps`: titles and commands at most 48 characters each.
- Headings: at most 60 characters.

## 10. Settings

- Theme: light by default. If the user asks for dark, add `--theme dark` (or `"theme": "dark"` in the storyboard).
- Format: wide (1920×1080) by default. If the user wants a vertical video, for a phone or for Shorts, add `--format tall` (1080×1920). The same storyboard works in both; preview it again in the format you will render.
- A `.i-dont-read.json` file in `--root` sets the user's defaults: `{ "theme": "dark", "format": "tall", "voice": "am_michael", "speed": 1.0, "captions": true }`. If the user wants a setting to stick, write it there.
- `python -m idr voices` lists the voices (the default is `af_heart`). `--voice NAME` picks one, `--no-captions` turns the burnt-in captions off, `--silent` renders without voice.
- Output is 30 fps, named `<storyboard>_<theme>.mp4` in `--out` (`<storyboard>_<theme>_tall.mp4` for the tall format).
