#!/usr/bin/env bash
# Regenerate the terminal screencasts shown in docs/tutorials.md.
#
#   scripts/make_screencasts.sh [OUTPUT_DIR] [CAST ...]
#
# OUTPUT_DIR defaults to a folder outside the repository
# (${TMPDIR:-/tmp}/cdlbib-screencasts). It may not be empty, /, your home
# folder, or a folder inside the repository. CAST is "check" (the default) or
# "commit". Needs vhs (https://github.com/charmbracelet/vhs) and an installed
# cdlbib on PATH.
#
# check   Copies cdl.bib and verification/ into OUTPUT_DIR/library, restores
#         the saved results there, and records `cdlbib verify --no-citations`
#         and `cdlbib crossref status cdl.bib`. The repository is not changed.
#         The script marks the library/ folder it creates with the file
#         .cdlbib-screencast-scratch and replaces only a library/ folder that
#         carries that marker; any other library/ folder stops the script.
#
# commit  Records a real `cdlbib commit`: it pushes a branch to a fork and
#         opens a real pull request from that fork into its parent repository.
#         It is recorded only when named, only from the checkout given in
#         CDLBIB_SCREENCAST_CHECKOUT (which must already hold the edit to
#         send), only when that checkout's origin is a GitHub repository not
#         owned by ContextLab, and only with the flag
#         --i-understand-this-opens-a-real-pull-request.
set -euo pipefail

marker=".cdlbib-screencast-scratch"
flag="--i-understand-this-opens-a-real-pull-request"
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"

understood=no
args=()
for arg in "$@"; do
  if [ "$arg" = "$flag" ]; then understood=yes; else args+=("$arg"); fi
done
set -- ${args[@]+"${args[@]}"}

if [ "$#" -gt 0 ]; then
  out="$1"
  shift
  [ -n "$out" ] || { echo "OUTPUT_DIR may not be empty" >&2; exit 1; }
else
  out="${TMPDIR:-/tmp}/cdlbib-screencasts"
fi
if [ "$#" -eq 0 ]; then set -- check; fi

case "$out" in
  /*) ;;
  *) out="$PWD/$out" ;;
esac
parent="$(dirname "$out")"
[ -d "$parent" ] || { echo "OUTPUT_DIR's parent folder does not exist: $parent" >&2; exit 1; }
base="$(basename "$out")"
parent="$(cd "$parent" && pwd -P)"
case "$base" in
  /|.) out="$parent" ;;
  ..) out="$(cd "$parent/.." && pwd -P)" ;;
  *) out="${parent%/}/$base" ;;
esac
home="$(cd "$HOME" && pwd -P)"
if [ -z "$out" ] || [ "$out" = "/" ] || [ "$out" = "$home" ]; then
  echo "OUTPUT_DIR may not be / or your home folder: ${out:-/}" >&2
  exit 1
fi
case "$out/" in
  "$repo"/*) echo "OUTPUT_DIR must be outside the repository: $out" >&2; exit 1 ;;
esac

for tool in vhs cdlbib; do
  command -v "$tool" >/dev/null || { echo "$tool was not found on PATH" >&2; exit 1; }
done

for cast in "$@"; do
  case "$cast" in
    check)
      library="$out/library"
      if [ -e "$library" ] || [ -L "$library" ]; then
        if [ -L "$library" ] || [ ! -f "$library/$marker" ]; then
          echo "check: $library exists and was not made by this script (no $marker file in it)." >&2
          echo "Nothing was removed. Choose another OUTPUT_DIR, or move that folder away." >&2
          exit 1
        fi
        rm -rf "$library"
      fi
      mkdir -p "$library"
      : > "$library/$marker"
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
      origin="$(git -C "$checkout" remote get-url origin 2>/dev/null || true)"
      owner="$(printf '%s\n' "$origin" | sed -nE 's#^(https?://([^@/]+@)?github\.com/|ssh://git@github\.com(:[0-9]+)?/|git@github\.com:|git://github\.com/)([^/:]+)/[^/]+$#\4#p')"
      if [ -z "$owner" ]; then
        echo "commit: the origin of $checkout is not a GitHub repository (${origin:-no origin}). Nothing was recorded." >&2
        exit 1
      fi
      if [ "$(printf '%s' "$owner" | tr '[:upper:]' '[:lower:]')" = "contextlab" ]; then
        echo "commit: the origin of $checkout is $origin, a ContextLab repository. Nothing was recorded." >&2
        echo "This cast is recorded only from a clone of a personal fork." >&2
        exit 1
      fi
      echo "commit: this cast runs a real \`cdlbib commit\` in $checkout." >&2
      echo "It will push a branch to the fork $origin and open a real pull request from that fork into its parent repository." >&2
      if [ "$understood" != yes ]; then
        echo "Nothing was recorded. To proceed, run again with $flag" >&2
        exit 1
      fi
      mkdir -p "$out"
      (cd "$checkout" && vhs -o "$out/commit.gif" "$repo/scripts/commit.tape")
      ;;
    *)
      echo "unknown cast: $cast (expected check or commit)" >&2
      exit 1
      ;;
  esac
  echo "$out/$cast.gif"
done
