# i-dont-read

**Don't read. Just watch.**

An agent skill that turns a codebase, a document, or any text into a short narrated explainer video.

> Status: early work in progress. The render engine works for one sample; the skill itself is not written yet.

## What it will do

- **Shows the real source.** Code and text are pulled straight from the files and highlighted on screen, not retyped.
- **Narrates it.** Local text-to-speech (Kokoro), so no API key is needed.
- **Adds sound effects** on transitions, highlights and reveals.
- **One idea per chapter.** Each element gets its own chapter with a hard cut, instead of one long run-on explanation.
- **Length follows the content**, not a fixed duration.
- **Light and dark themes.**

## How it works

1. Read the source and split it into chapters.
2. Write narration and screen directions for each chapter.
3. Synthesize the narration sentence by sentence.
4. Time the visuals to the actual audio.
5. Film each chapter as an HTML scene in headless Chrome and encode it with ffmpeg.
6. Mix in sound effects and join the chapters.

## Try the sample

```bash
pip install -r requirements.txt
python -m idr render examples/self/storyboard.json --root . --out out            # light
python -m idr render examples/self/storyboard.json --root . --out out --theme dark
```

The sample explains this repo's own filming loop. The first run downloads the voice model (about 350 MB) into `~/.cache/i-dont-read`.

Add `--stills` to draw a few preview frames instead of filming.

## Settings

Theme and voice are picked in this order: command line flag, then the storyboard, then a `.i-dont-read.json` file in the project root, then the defaults (`light`, `af_heart`).

```json
{ "theme": "dark", "voice": "af_heart" }
```

## Requirements

- Python 3.10+
- ffmpeg
- Google Chrome or Chromium

## License

MIT
