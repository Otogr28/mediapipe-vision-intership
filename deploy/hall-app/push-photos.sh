#!/usr/bin/env bash
# Fill the exhibit's idle slideshow from a folder of photographs on the laptop.
# Run on the laptop, from anywhere:
#
#   deploy/hall-app/push-photos.sh                    # the default folder
#   deploy/hall-app/push-photos.sh ~/Pictures/hall    # some other folder
#
# What it does: downscale every image into a staging folder, then rsync that
# to ~/hall-photos on the Jetson, which is the directory the app reads its
# slideshow from (config.ATTRACT_GALLERY_DIR / HALL_ATTRACT_DIR). The running
# kiosk rescans that folder once a minute, so new photographs appear WITHOUT
# a restart, a redeploy or a commit.
#
# Why this is not `git push`: the exhibit updates itself from git, but these
# are photographs of people and the repository is public. They live on the
# device only. The cost is that a reflashed Jetson needs this script run
# again — which is one command, and is why it exists as a script.
#
# The downscale is not optional dressing. Straight off a phone these are 3-6
# MB each at 4000x3000; the Orin decodes every one of them at full size into
# an 8 GB pool it shares with the GPU and the browser, to draw it at 1280x720.
# Capping the long side at 1920 costs nothing visible on the exhibit monitor
# and turns 145 MB into about 25.
#
# Override the target with:  JETSON_HOST=jetson@<ip> deploy/hall-app/push-photos.sh
set -euo pipefail

SRC="${1:-$HOME/Documents/Pictures/Intership2026Pictures/photos}"
JETSON_HOST="${JETSON_HOST:-jetson@100.91.206.114}"
REMOTE_DIR="${HALL_PHOTOS_REMOTE:-hall-photos}"   # relative to the remote $HOME
MAX_SIDE="${HALL_PHOTO_MAX_SIDE:-1920}"
QUALITY="${HALL_PHOTO_QUALITY:-85}"

if [ ! -d "$SRC" ]; then
  echo "!! no such folder: $SRC" >&2
  exit 1
fi

# ImageMagick 7 renamed the entry point; accept either.
if command -v magick >/dev/null 2>&1; then
  IM=(magick)
elif command -v convert >/dev/null 2>&1; then
  IM=(convert)
else
  echo "!! ImageMagick not found — install it (pacman -S imagemagick)" >&2
  exit 1
fi

STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

echo ">> downscaling $SRC (long side ${MAX_SIDE}px, q${QUALITY})"
count=0
skipped=0
shopt -s nullglob nocaseglob
for f in "$SRC"/*.jpg "$SRC"/*.jpeg "$SRC"/*.png "$SRC"/*.webp; do
  [ -s "$f" ] || { skipped=$((skipped + 1)); continue; }   # zero-byte file
  base="$(basename "$f")"
  # Spaces and parentheses survive the trip (the app percent-encodes them for
  # its own HTTP route), but the extension is normalised so the slideshow's
  # filename sort is not split by case.
  out="$STAGE/${base%.*}.jpg"
  # A folder holding both `x.png` and `x.jpg` would collapse to one file
  # here, and the slide that vanished would be a puzzle to debug later.
  n=2
  while [ -e "$out" ]; do out="$STAGE/${base%.*}-$n.jpg"; n=$((n + 1)); done
  # -auto-orient FIRST: phone photographs carry their rotation in EXIF, and
  # -strip throws that tag away, so the wrong order lands every portrait shot
  # on its side. '>' means shrink-only — a small photograph is left alone
  # rather than blown up into a blurry one.
  if ! "${IM[@]}" "$f" -auto-orient -resize "${MAX_SIDE}x${MAX_SIDE}>" \
       -quality "$QUALITY" -strip "$out" 2>/dev/null; then
    echo "   skipped (unreadable): $base"
    skipped=$((skipped + 1))
    continue
  fi
  count=$((count + 1))
done
shopt -u nullglob nocaseglob

if [ "$count" -eq 0 ]; then
  echo "!! no usable images in $SRC" >&2
  exit 1
fi
note=""
[ "$skipped" -gt 0 ] && note=", $skipped skipped"
echo "   $count image(s), $(du -sh "$STAGE" | cut -f1)$note"

# Check the downscale without a Jetson in the room:
#   HALL_PHOTO_STAGE_ONLY=/tmp/hall-stage deploy/hall-app/push-photos.sh
# Point mock_backend.py at that folder (HALL_ATTRACT_DIR) to see the result.
if [ -n "${HALL_PHOTO_STAGE_ONLY:-}" ]; then
  mkdir -p "$HALL_PHOTO_STAGE_ONLY"
  rsync -a --delete "$STAGE/" "$HALL_PHOTO_STAGE_ONLY/"
  echo ">> staged locally in $HALL_PHOTO_STAGE_ONLY (nothing sent)"
  exit 0
fi

echo ">> syncing to ${JETSON_HOST}:~/${REMOTE_DIR}"
ssh "$JETSON_HOST" "mkdir -p ~/$REMOTE_DIR"
# --delete so removing a photograph here removes it from the exhibit too:
# this folder is a mirror of $SRC, not an accumulating pile.
rsync -az --delete --info=stats1 "$STAGE/" "$JETSON_HOST:~/$REMOTE_DIR/"

echo ">> done. The kiosk rescans once a minute — no restart needed."
echo "   To check what it sees:  ssh $JETSON_HOST ls ~/$REMOTE_DIR | wc -l"
