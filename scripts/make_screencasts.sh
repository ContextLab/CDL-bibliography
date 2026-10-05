#!/usr/bin/env bash
# Regenerate the terminal screencasts shown in docs/tutorials/.
#
#   scripts/make_screencasts.sh [OUTPUT_DIR] [CAST ...]
#
# OUTPUT_DIR defaults to docs/media in this repository. It may not be empty,
# /, your home folder, or any other folder inside the repository. CAST is
# "check" (the default) or "send". Needs vhs
# (https://github.com/charmbracelet/vhs) and an installed cdlbib on PATH.
#
# check   Copies cdl.bib and verification/ into a temporary folder made with
#         mktemp outside the repository, restores the saved results there, and
#         records `cdlbib verify --no-citations` and
#         `cdlbib crossref status cdl.bib` as OUTPUT_DIR/check.gif. The
#         temporary folder is removed when the script ends. Nothing else is
#         removed, and cdl.bib and verification/ are not changed.
#
# send    Records a real `cdlbib send`: it pushes a branch to a fork and
#         opens a real pull request from that fork into its parent repository.
#         It is recorded only when named, only from the checkout given in
#         CDLBIB_SCREENCAST_CHECKOUT (which must already hold the edit to
#         send), only when that checkout's origin is a GitHub repository not
#         owned by ContextLab, and only with the flag
#         --i-understand-this-opens-a-real-pull-request.
set -euo pipefail

flag="--i-understand-this-opens-a-real-pull-request"
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
media="$repo/docs/media"

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
  out="$media"
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
if [ -d "$out" ]; then out="$(cd "$out" && pwd -P)"; fi
home="$(cd "$HOME" && pwd -P)"
if [ -z "$out" ] || [ "$out" = "/" ] || [ "$out" = "$home" ]; then
  echo "OUTPUT_DIR may not be / or your home folder: ${out:-/}" >&2
  exit 1
fi
if [ "$out" != "$media" ]; then
  case "$out/" in
    "$repo"/*) echo "Inside the repository, OUTPUT_DIR may only be $media (got $out)" >&2; exit 1 ;;
  esac
fi

for tool in vhs cdlbib; do
  command -v "$tool" >/dev/null || { echo "$tool was not found on PATH" >&2; exit 1; }
done

scratch=""
remove_scratch() {
  if [ -n "$scratch" ] && [ -d "$scratch" ]; then rm -rf "$scratch"; fi
}
trap remove_scratch EXIT

for cast in "$@"; do
  case "$cast" in
    check)
      scratch="$(mktemp -d "${TMPDIR:-/tmp}/cdlbib-screencast.XXXXXX")"
      scratch="$(cd "$scratch" && pwd -P)"
      case "$scratch/" in
        "$repo"/*) echo "check: the temporary folder $scratch is inside the repository; set TMPDIR to a folder outside it." >&2; exit 1 ;;
      esac
      library="$scratch/library"
      mkdir "$library"
      cp "$repo/cdl.bib" "$library/"
      cp -R "$repo/verification" "$library/verification"
      (cd "$library" && env -u CDLBIB_LIBRARY -u CDLBIB_HOME -u CDLBIB_UPSTREAM cdlbib --library "$library" crossref restore verification/baseline.jsonl.gz >/dev/null)
      mkdir -p "$out"
      (cd "$library" && env -u CDLBIB_HOME -u CDLBIB_UPSTREAM CDLBIB_LIBRARY="$library" vhs -o "$out/check.gif" "$repo/scripts/check.tape")
      remove_scratch
      scratch=""
      ;;
    send)
      checkout="${CDLBIB_SCREENCAST_CHECKOUT:-}"
      if [ -z "$checkout" ] || [ ! -f "$checkout/cdl.bib" ]; then
        echo "send: set CDLBIB_SCREENCAST_CHECKOUT to a checkout that holds the edit to send." >&2
        echo "This cast runs a real \`cdlbib send\`: it pushes a branch and opens a pull request." >&2
        exit 1
      fi
      origin="$(git -C "$checkout" remote get-url origin 2>/dev/null || true)"
      owner="$(printf '%s\n' "$origin" | sed -nE 's#^(https?://([^@/]+@)?github\.com/|ssh://git@github\.com(:[0-9]+)?/|git@github\.com:|git://github\.com/)([^/:]+)/[^/]+$#\4#p')"
      if [ -z "$owner" ]; then
        echo "send: the origin of $checkout is not a GitHub repository (${origin:-no origin}). Nothing was recorded." >&2
        exit 1
      fi
      if [ "$(printf '%s' "$owner" | tr '[:upper:]' '[:lower:]')" = "contextlab" ]; then
        echo "send: the origin of $checkout is $origin, a ContextLab repository. Nothing was recorded." >&2
        echo "This cast is recorded only from a clone of a personal fork." >&2
        exit 1
      fi
      echo "send: this cast runs a real \`cdlbib send\` in $checkout." >&2
      echo "It will push a branch to the fork $origin and open a real pull request from that fork into its parent repository." >&2
      if [ "$understood" != yes ]; then
        echo "Nothing was recorded. To proceed, run again with $flag" >&2
        exit 1
      fi
      mkdir -p "$out"
      (cd "$checkout" && vhs -o "$out/send.gif" "$repo/scripts/send.tape")
      ;;
    *)
      echo "unknown cast: $cast (expected check or send)" >&2
      exit 1
      ;;
  esac
  echo "$out/$cast.gif"
done
