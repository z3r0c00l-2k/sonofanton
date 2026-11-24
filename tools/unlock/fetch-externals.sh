#!/usr/bin/env bash
# Fetch the external tools at their pinned revisions.
# Does not fetch firmware or keys, and does not write into the repository.
set -euo pipefail

WORK="${R9S_WORK:-$PWD}"
EXYNOS_PIN="176146dd3b0b22049acd2963d9fa69e64ac1654c"
HOUSTON_PIN="ec3135de1837cd27f8cf3e512933179fd4c849d7"

mkdir -p "$WORK"

clone_pin() {
    local url="$1" dir="$2" pin="$3"
    if [ ! -d "$dir/.git" ]; then
        git clone "$url" "$dir"
    fi
    git -C "$dir" fetch --quiet --all --tags
    git -C "$dir" checkout --quiet "$pin"
    printf 'ok  %s @ %s\n' "$dir" "$(git -C "$dir" rev-parse --short HEAD)"
}

clone_pin https://github.com/henr1kas/Exynos.git "$WORK/Exynos" "$EXYNOS_PIN"
clone_pin https://github.com/halal-beef/houston-pub.git "$WORK/houston-pub" "$HOUSTON_PIN"

cat <<EOF

Next:
  1. Put your split firmware images in $WORK/input/.
  2. Generate your keys in $WORK/keys/ (see docs/unlock/04-keys-and-fuse.md).
  3. Read docs/recovery-first.md before flashing anything.

Odin is not downloaded; obtain it from Samsung and verify it.
EOF
