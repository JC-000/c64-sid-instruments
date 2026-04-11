#!/usr/bin/env bash
# Regenerate comparisons/fur_elise_ours_8580.wav using the current
# (post-PR #25 baseline-restore) grand-piano 8580 params.
#
# This is a one-shot evaluation-artifact script, not a reusable feature.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

python3 tools/render_fur_elise.py \
    --params instruments/grand-piano/8580/grand-piano-8580-params.json \
    --notes comparisons/fur_elise_notes.json \
    --chip 8580 \
    --out comparisons/fur_elise_ours_8580.wav
