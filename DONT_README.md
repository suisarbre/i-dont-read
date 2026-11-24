# Don't README

The README of this repository is four videos: what this is, how to install it, how to use it, and what to do when something goes wrong. This file says the same things in writing, for people and agents who would rather read.

**i-dont-read** is an agent skill that turns a codebase, a document, a change or a web page into a short narrated explainer video.

## What it does

- **Shows the real source.** Code and text are read straight from the files by line range and highlighted on screen. Nothing is retyped.
- **Narrates it.** A local voice model (Kokoro) speaks every sentence, so no account or API key is needed.
- **Adds sound effects** on scene changes, highlights and reveals. All of them are synthesized in this repo.
- **One idea per chapter.** Each idea gets its own chapter with a title card and a hard cut, and the mp4 carries real chapter markers.
- **Length follows the content.** There is no fixed duration.
- **Changes too.** Asked about a commit, a branch or a pull request, it shows the real diff and explains what changed and how it worked before. The why is taken only from what the author wrote.
- **Web pages and PDFs too.** A page is photographed in a real browser, the way a reader would see it, and the camera zooms to words it finds there. A consent dialog is closed by pressing its own button; a page that stops at a login or subscription wall is explained only as far as it can be read.
- **Timed to the word.** The voice model reports when each word is spoken, so a highlight can land on a word in the middle of a sentence.
- **Light and dark themes, wide and tall formats.** 1920×1080 by default, 1080×1920 for a phone.
- **Video is the whole answer.** No summary under it, no outline to approve. When something is missing on the machine, even the fix arrives as a video.

## Install

As a skill for Claude Code:

```bash
git clone https://github.com/suisarbre/i-dont-read ~/.claude/skills/i-dont-read
pip install -r ~/.claude/skills/i-dont-read/requirements.txt
```

You also need `ffmpeg` and Google Chrome or Chromium. Then check the machine from the skill's folder:

```bash
python -m idr doctor
```

It prints one line for each of the four things a render needs, and `ready` when all of them are there. The first render downloads the voice model (about 350 MB) into `~/.cache/i-dont-read`.

## Use it

Ask the agent for a video and point at the thing: "explain this repo as a video", "make a video of this document", "explain what this branch changes, as a video", "explain this page as a video". It can be a folder, a file, a commit or pull request, a web address, a PDF, or text pasted into the chat.

The reply is the video and one caption line with its title and length. To change it, say what to change: scenes that stay the same are not filmed again.

Say "dark" for the dark theme and "vertical" for a 1080×1920 video. To make a choice stick, put it in a `.i-dont-read.json` file in the project root:

```json
{ "theme": "dark", "format": "tall", "voice": "am_michael", "speed": 1.0, "captions": true }
```

A setting is picked in this order: command line flag, then the storyboard, then that file, then the defaults.

## When something goes wrong

`python -m idr doctor` checks the Python packages, ffmpeg, the browser and the voice model. For each one that is missing it names a ready-made video in `help/` that explains the fix, and the skill sends that video instead of an error message.

| Missing | The fix |
|---|---|
| ffmpeg | `brew install ffmpeg`, `winget install ffmpeg` or `sudo apt install ffmpeg` |
| A browser | Install Google Chrome, or `python -m playwright install chromium` |
| Python packages | `pip install -r requirements.txt` |
| The voice model | Allow downloads from github.com, or put the two model files in `~/.cache/i-dont-read/` |

If only the voice model is unavailable, `render --silent` still makes a video, with captions carrying the narration. If the machine has no font for some characters on screen, the render says which, and installing a font that covers them (Noto Sans CJK for Korean, Japanese and Chinese) fixes it.

A web page that needs a login cannot be opened, and neither can one the network blocks: save the page as an `.html` file or a PDF and point at that instead. A page that stops at a subscription wall is explained only up to the wall, and the caption says so. A consent dialog over the page is closed the way a reader would close it, by pressing its own button.

The help videos are rendered from the storyboards beside them; `sh help/build.sh` rebuilds them.

## With no source, and follow-up questions

Give it a topic instead of a source ("explain Taylor series as a video") and it explains from what it knows; the opening card then says there is no source document. Ask a question about a video it made and the answer is another short video: it shows the place in the source the question is about, and anything it adds that the source does not say is labelled "beyond the source" on screen. Code it writes to illustrate a point is labelled as an example written for the video, never as one of your files.

## Other ways to install

The clone in "Install" is all Claude Code needs. Two other routes put the same folder in place:

- As a Claude Code plugin: `claude plugin marketplace add suisarbre/i-dont-read`, then `claude plugin install i-dont-read@i-dont-read`. The skill then shows up as `i-dont-read:i-dont-read`.
- With the skills installer, for any agent that reads `SKILL.md`: `npx skills add suisarbre/i-dont-read`.

Either way the Python packages, ffmpeg and a browser are still yours to install, and `python -m idr doctor` still tells you what is missing. Only Claude has been tried so far.

## How it works

The agent reads the source, splits it into chapters, and writes a storyboard: a JSON file listing the scenes, the sentences to speak, and what to show during each sentence. The engine in `idr/` does the rest.

1. Speak every sentence and measure how long it takes.
2. Time the visuals to the audio, so each highlight lands when its sentence starts.
3. Draw each scene as an HTML page in headless Chrome and film it frame by frame.
4. Mix narration and sound effects, then join the scenes.

Scene types: `code`, `diff`, `quote`, `image`, `flow`, `compare`, `stats`, `steps`, `math`, `table` (formulas and tables, with `$...$` math typeset by a bundled KaTeX in any scene text) and `plot` (graphs of functions, parameter, polar and equation curves, with points, tangents, secants, areas that can grow, Riemann sums, arrows, area functions and curves that change, every number computed from the formulas and quotable in the narration). `SKILL.md` documents the storyboard format and is what the agent follows.

## Use the engine directly

```bash
python -m idr doctor                                             # is this machine ready to render?
python -m idr check   examples/self/storyboard.json --root .    # validate and estimate length
python -m idr preview examples/self/storyboard.json --root .    # one frame per scene, to look at
python -m idr preview examples/self/storyboard.json --root . --beats   # one frame per change on screen
python -m idr render  examples/self/storyboard.json --root .    # make out/storyboard_light.mp4
python -m idr render  examples/self/storyboard.json --root . --theme dark
python -m idr render  examples/self/storyboard.json --root . --format tall
python -m idr voices
python -m idr sounds "PyPI" "memtable"      # how the voice will pronounce something, in IPA
```

`examples/self` explains this repo with this repo. `examples/showcase` shows a diff, a web page, a PDF, an image and word-timed highlights. `examples/commit` explains one of this repo's own commits (it needs the full git history, so it will not check in a shallow clone). `examples/kokoro-onnx` explains [kokoro-onnx](https://github.com/thewh1teagle/kokoro-onnx), the voice library used here; clone that repo and pass it as `--root` (line numbers match its commit `3596b26`, and the render stops with a clear error if they have moved).

The four README videos are in `readme/`, each beside the storyboard it was rendered from; `sh readme/build.sh` rebuilds them.

## Limits

- Narration is English only for now.
- The tall format is a first version: every scene works, but layouts are tuned for wide.
- A web page is captured 1440 px wide and up to 3600 px tall at a time. A page that needs a login cannot be opened; a saved copy of it can.

## License

MIT. Bundled fonts (Source Serif 4, Inter, JetBrains Mono) are under the SIL Open Font License; see `idr/web/fonts`.
