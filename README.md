# i-dont-read

**Don't read. Just watch.**

An agent skill that turns a codebase, a document, or any text into a short narrated explainer video.

## What it does

- **Shows the real source.** Code and text are read straight from the files by line range and highlighted on screen. Nothing is retyped.
- **Narrates it.** A local voice model (Kokoro) speaks every sentence, so no account or API key is needed.
- **Adds sound effects** on scene changes, highlights and reveals. All of them are synthesized in this repo.
- **One idea per chapter.** Each idea gets its own chapter with a title card and a hard cut, and the mp4 carries real chapter markers.
- **Length follows the content.** There is no fixed duration.
- **Light and dark themes.**
- **Video is the whole answer.** No summary under it, no outline to approve. When something is missing on the machine, even the fix arrives as a video.

## Install as a skill

Claude Code:

```bash
git clone https://github.com/suisarbre/i-dont-read ~/.claude/skills/i-dont-read
pip install -r ~/.claude/skills/i-dont-read/requirements.txt
```

Then ask for it: "explain this repo as a video", "make a video of this document".

You also need `ffmpeg` and Google Chrome or Chromium. The first render downloads the voice model (about 350 MB) into `~/.cache/i-dont-read`.

## How it works

The agent reads the source, splits it into chapters, and writes a storyboard: a JSON file listing the scenes, the sentences to speak, and what to show during each sentence. The engine in `idr/` does the rest.

1. Speak every sentence and measure how long it takes.
2. Time the visuals to the audio, so each highlight lands when its sentence starts.
3. Draw each scene as an HTML page in headless Chrome and film it frame by frame.
4. Mix narration and sound effects, then join the scenes.

Scene types: `code`, `quote`, `flow`, `compare`, `stats`, `steps`. `SKILL.md` documents the storyboard format.

## Use the engine directly

```bash
python -m idr doctor                                             # is this machine ready to render?
python -m idr check   examples/self/storyboard.json --root .    # validate and estimate length
python -m idr preview examples/self/storyboard.json --root .    # one frame per scene, to look at
python -m idr render  examples/self/storyboard.json --root .    # make out/storyboard_light.mp4
python -m idr render  examples/self/storyboard.json --root . --theme dark
python -m idr voices
```

`examples/self` explains this repo with this repo. `examples/kokoro-onnx` explains [kokoro-onnx](https://github.com/thewh1teagle/kokoro-onnx), the voice library used here; clone that repo and pass it as `--root` (line numbers match its commit `3596b26`, and the render stops with a clear error if they have moved).

## When something is missing

`python -m idr doctor` checks the Python packages, ffmpeg, the browser and the voice model. For each problem it names a ready-made video in `help/` that explains the fix, and the skill sends that video instead of an error message. If only the voice model is unavailable, `render --silent` still makes a captioned video.

The help videos are rendered from the storyboards beside them; `sh help/build.sh` rebuilds them.

## Settings

Theme, voice, speed and captions are picked in this order: command line flag, then the storyboard, then a `.i-dont-read.json` file in the project root, then the defaults.

```json
{ "theme": "dark", "voice": "am_michael", "speed": 1.0, "captions": true }
```

## Limits

- Narration is English only for now.
- Output is 1920×1080 at 30 fps.

## License

MIT. Bundled fonts (Source Serif 4, Inter, JetBrains Mono) are under the SIL Open Font License; see `idr/web/fonts`.
