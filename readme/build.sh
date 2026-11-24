#!/bin/sh
# Re-render the four README videos. Run from the repo root after changing a storyboard here, the
# files they show (DONT_README.md, idr/render.py, idr/plan.py) or the player.
set -e
for name in 1-what-it-does 2-install 3-use-it 4-when-something-goes-wrong; do
  python -m idr render "readme/$name.json" --root . --out readme/.out --name "$name"
  cp "readme/.out/${name}_light.mp4" "readme/$name.mp4"
done
rm -rf readme/.out
