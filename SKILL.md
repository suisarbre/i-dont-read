---
name: i-dont-read
description: Turn a codebase, file, document, article or pasted text into a short narrated explainer video (mp4) that shows the real source on screen with highlights, infographics, voice-over, sound effects and chapters. Use when the user says "explain this as a video", "make a video about this repo / file / doc", "I don't want to read this, show me".
---

# I don't read

The user does not want to read the thing. You read it, decide what matters, and hand back a video that explains it: one idea per chapter, the real source on screen, a voice talking over it.

You write a **storyboard** (a JSON file). The engine in `idr/` turns it into an mp4: it speaks every sentence with a local voice model, times the visuals to the audio, films each scene in headless Chrome, and mixes in sound effects.

## 1. Find the engine

The engine is the `idr/` folder next to this file. If it is not there (the skill was saved as this file alone), get it once per session:

```bash
git clone --depth 1 https://github.com/suisarbre/i-dont-read ~/i-dont-read
```

Call that folder `ENGINE`. Then:

```bash
pip install -r ENGINE/requirements.txt      # add --break-system-packages if pip asks for it
```

It also needs `ffmpeg` and Chrome or Chromium (set `IDR_CHROME` to the binary if it is not found). Run every command below from `ENGINE` as `python -m idr ...`. The first render downloads the voice model, about 350 MB, into `~/.cache/i-dont-read`; if that download is blocked, say so and stop.

## 2. Workflow

1. **Read the source yourself, properly.** For a codebase: the README, the entry points, and the handful of files that carry the design. For a document: all of it. If the user pasted text into the chat, save it to a file first (`work/source.md`), because scenes can only show text that is in a file.
2. **Choose the chapters.** A chapter is one idea the viewer should walk away with. Explain one thing per chapter and cut; do not chain several ideas together. Most sources need 2 to 5 chapters. Let the content set the length: do not pad a small thing or cram a large one.
3. **If the choice of chapters is a real judgment call** (a large codebase, a long document, or the user asked about "this repo" with no focus), show the outline first: chapter titles with one line each. Wait for a yes. For a small or clearly scoped source, skip this and build.
4. **Write `work/storyboard.json`** (format in section 3).
5. **Check it:** `python -m idr check work/storyboard.json --root SOURCE_DIR`. Fix every error and every warning.
6. **Look at it before filming:** `python -m idr preview work/storyboard.json --root SOURCE_DIR --out work/out`, then open the contact sheets it lists. Fix anything cramped, clipped or wrapped badly, and any note that covers code.
7. **Render once:** `python -m idr render work/storyboard.json --root SOURCE_DIR --out work/out`. A render keeps the user waiting, so do not render to "see how it looks"; that is what `preview` is for.
8. **Hand over the mp4** with its length and chapter list (the render prints both). Do not describe the video scene by scene.

To change a finished video, edit the storyboard and render again. Scenes that did not change are reused and sentences that did not change are not re-spoken.

`--root` is the folder that `file` paths in the storyboard are relative to: the root of the repo or the folder holding the document.

## 3. Storyboard format

```json
{
  "title": "How the cache works",
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

Optional top-level fields: `theme` (`light` or `dark`), `voice`, `speed`, `captions`, and `intro` (`{ "say": "...", "sub": "..." }`) for an opening card that shows `title`.

Each chapter opens with a title card that shows `title` and speaks `say`. Then its scenes play in order.

A **beat** is one spoken sentence plus what changes on screen when that sentence starts. Every scene has a `heading` and a list of `beats`.

| Scene | Use it when | Fields | What a beat can do |
|---|---|---|---|
| `code` | The point is in specific lines | `file`, `lines: [first, last]`, `expect` | `highlight`: a line number or `[first, last]` (stays until changed; `null` clears). `note`: a short label beside the highlight |
| `quote` | The source says it best in its own words | `file`, `lines: [first, last]` | `mark`: a phrase, or a list of phrases, to run a marker over |
| `flow` | A process, pipeline or sequence of parts | `nodes: [{ "label", "desc" }]` (2 to 6) | `reveal`: how many nodes are visible from now on. `focus`: which node (1-based) gets the ring |
| `compare` | Two options, or before and after | `columns: [{ "title", "points": [] }, { ... }]` (exactly 2, up to 5 rows) | `reveal`: how many rows are visible from now on |
| `stats` | The numbers are the story | `items: [{ "value", "label", "note" }]` (1 to 4) | `reveal`: how many cards are visible from now on |

Any beat can also carry `speak` (see section 4) or, with no `say`, a `hold` in seconds.

A chapter is usually 1 to 3 scenes. Alternate real source (`code`, `quote`) with an infographic (`flow`, `compare`, `stats`) that puts it in context.

## 4. Writing the narration

- One sentence per beat, about 25 words at most. Write it to be heard, not read.
- Say what the highlighted thing does and why it matters. Never read code aloud.
- The picture must match the words: put the `highlight`, `mark` or `reveal` on the beat whose sentence is about it.
- The voice mispronounces identifiers, paths and symbols. When a sentence needs one, keep `say` as it should appear in the caption and add `speak` with how to pronounce it: `"say": "It calls parse_args() first."`, `"speak": "It calls parse args first."`
- A chapter's `say` is a hook: the question the chapter answers, or its promise in one line.
- Start with the content. No "in this video" and no "let's dive in". End the last chapter on the takeaway.
- Narration is English only for now. If the user wants another language, tell them that and offer English.

## 5. Stay truthful

This is the reason the skill exists, so do not work around it.

- `code` and `quote` scenes show only what is in the file at those lines. Never paste code or prose into the storyboard.
- Always set `expect` on a `code` scene to a short string from the first line you care about. The render stops if the lines moved.
- A `mark` must be copied exactly from the quoted lines. The render stops if it is not found.
- Every number in a `stats` scene and every claim in a `compare` scene must come from the source. Put where it came from in `note` when you can.
- If the source does not say something, the video does not say it either.

## 6. Limits the check enforces

- `code`: at most 16 lines per scene, and 12 or fewer reads best; lines over about 96 columns are cut off. Pick the lines that matter and split long passages into two scenes.
- `quote`: at most 640 characters. Quote the paragraph that matters, not the page.
- `flow` labels: about 12 characters with 5 or 6 nodes, 18 with fewer.
- `stats` values: at most 10 characters. Put the words in `label`.
- Headings: at most 60 characters.

## 7. Settings

- Theme: light by default. If the user asks for dark, add `--theme dark` (or `"theme": "dark"` in the storyboard).
- A `.i-dont-read.json` file in `--root` sets the user's defaults: `{ "theme": "dark", "voice": "am_michael", "speed": 1.0, "captions": true }`. If the user wants a setting to stick, write it there.
- `python -m idr voices` lists the voices. `--voice NAME` picks one, `--no-captions` turns the burnt-in captions off.
- Output is 1920×1080 at 30 fps, named `<storyboard>_<theme>.mp4` in `--out`.
