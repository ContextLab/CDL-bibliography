#!/usr/bin/env bash
# Regenerate the terminal screencasts shown in docs/tutorials.md.
#
#   scripts/make_screencasts.sh [OUTPUT_DIR] [CAST ...]
#
# OUTPUT_DIR defaults to a folder outside the repository
# (${TMPDIR:-/tmp}/cdlbib-screencasts). CAST is "check" (the default) or
# "commit". Needs vhs (https://github.com/charmbracelet/vhs) and an installed
# cdlbib on PATH.
#
# check   Copies cdl.bib and verification/ into OUTPUT_DIR/library, restores
#         the saved results there, and records `cdlbib verify --no-citations`
#         and `cdlbib crossref status cdl.bib`. The repository is not changed.
#
# commit  Records a real `cdlbib commit`, which pushes a branch and opens a
#         pull request. It is recorded only when named, and only from the
#         checkout given in CDLBIB_SCREENCAST_CHECKOUT, which must already
#         hold the edit to send.
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
out="${1:-${TMPDIR:-/tmp}/cdlbib-screencasts}"
if [ "$#" -gt 0 ]; then shift; fi
if [ "$#" -eq 0 ]; then set -- check; fi

for tool in vhs cdlbib; do
  command -v "$tool" >/dev/null || { echo "$tool was not found on PATH" >&2; exit 1; }
done

case "$out" in
  /*) ;;
  *) out="$PWD/$out" ;;
esac
parent="$(dirname "$out")"
[ -d "$parent" ] || { echo "OUTPUT_DIR's parent folder does not exist: $parent" >&2; exit 1; }
out="$(cd "$parent" && pwd -P)/$(basename "$out")"
case "$out/" in
  "$(cd "$repo" && pwd -P)"/*) echo "OUTPUT_DIR must be outside the repository: $out" >&2; exit 1 ;;
esac
mkdir -p "$out"

for cast in "$@"; do
  case "$cast" in
    check)
      library="$out/library"
      rm -rf "$library"
      mkdir -p "$library"
      cp "$repo/cdl.bib" "$library/"
      cp -R "$repo/verification" "$library/verification"
      (cd "$library" && cdlbib crossref restore verification/baseline.jsonl.gz >/dev/null)
      (cd "$library" && vhs -o "$out/check.gif" "$repo/scripts/check.tape")
      ;;
    commit)
      checkout="${CDLBIB_SCREENCAST_CHECKOUT:-}"
      if [ -z "$checkout" ] || [ ! -f "$checkout/cdl.bib" ]; then
        echo "commit: set CDLBIB_SCREENCAST_CHECKOUT to a checkout that holds the edit to send." >&2
        echo "This cast runs a real \`cdlbib commit\`: it pushes a branch and opens a pull request." >&2
        exit 1
      fi
      (cd "$checkout" && vhs -o "$out/commit.gif" "$repo/scripts/commit.tape")
      ;;
    *)
      echo "unknown cast: $cast (expected check or commit)" >&2
      exit 1
      ;;
  esac
  echo "$out/$cast.gif"
done
