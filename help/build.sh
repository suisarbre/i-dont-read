#!/bin/sh
# Re-render the help videos. Run from the repo root after changing a help storyboard or the player.
set -e
for name in ffmpeg chrome packages voice-model; do
  python -m idr render "help/$name.json" --out help/.out --name "$name"
  cp "help/.out/${name}_light.mp4" "help/$name.mp4"
done
rm -rf help/.out
