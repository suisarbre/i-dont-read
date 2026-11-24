# i-dont-read

**Don't read. Just watch.**

An agent skill that turns a codebase, a document, or any text into a short narrated explainer video.

> Status: early work in progress. Nothing here is usable yet.

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

## Requirements

- Python 3.10+
- ffmpeg
- Google Chrome or Chromium

## License

MIT
