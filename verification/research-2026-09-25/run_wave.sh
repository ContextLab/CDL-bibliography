#!/bin/zsh
# Deterministic stages for one research wave, each gated on the previous one:
#   validate quotes -> post-check -> (independent review is a separate agent) -> review page.
# Usage: verification/research-2026-09-25/run_wave.sh verification/research-2026-09-25/wave4 [--page]
set -e
wave=${1:?wave folder}
root=${0:A:h:h:h}
cd "$root"
.venv/bin/python verification/research-pilot-2026-09-24/validate.py "$wave" | head -1 &&
.venv/bin/python verification/research-2026-09-25/postcheck.py "$wave" > "$wave/postcheck.log" &&
echo "post-check: $(grep -c '' "$wave/postcheck.log") log lines; merged: $(.venv/bin/python -c "import json;print(len(json.load(open('$wave/merged.json'))))") entries" &&
if [[ "$2" == "--page" ]]; then
  [[ -f "$wave/review.json" ]] || { echo "no review.json yet: run the independent review first" >&2; exit 1; }
  .venv/bin/python verification/research-2026-09-25/postcheck.py "$wave" > "$wave/postcheck.log" &&
  .venv/bin/python verification/research-2026-09-25/build_review.py "$wave"
fi
