#!/bin/bash
# Run a command on Linux as the `test` job of .github/workflows/autocheck.yml does: in a
# shallow checkout (depth 1, as actions/checkout makes) of this repository's HEAD, as a user
# who is not root, with the package installed from that checkout.
#
#   scripts/ci-linux/run.sh [-p 3.11|3.13] [-c CPUS] [-w] [-e NAME=VALUE]... [-s SCRIPT] [COMMAND...]
#
# -p  the Python (default 3.13)          -c  the CPUs given (default 2, as GitHub gives)
# -w  also copy in the changes of the working tree that are not committed yet
# -e  an environment variable for the command (may be repeated)
# -s  a shell script of this computer to run there (COMMAND... are then its arguments)
# Without COMMAND: `cdlbib verify --no-citations && python -m pytest -q -rs tests`.
set -eu
here=$(cd "$(dirname "$0")" && pwd)
repo=$(git -C "$here" rev-parse --show-toplevel)
python=3.13 cpus=2 dirty=no
options=()
while getopts p:c:we:s: option; do
  case $option in
    p) python=$OPTARG ;;
    c) cpus=$OPTARG ;;
    w) dirty=yes ;;
    e) options+=(-e "$OPTARG") ;;
    s) options+=(-v "$(cd "$(dirname "$OPTARG")" && pwd)/$(basename "$OPTARG"):/script.sh:ro")
       script=yes ;;
    *) exit 2 ;;
  esac
done
shift $((OPTIND - 1))
if [ -n "${script:-}" ]; then
  set -- bash /script.sh "$@"
elif [ $# -eq 0 ]; then
  set -- sh -c 'cdlbib verify --no-citations && python -m pytest -q -rs tests'
fi

docker image inspect cdlbib-ci-linux >/dev/null 2>&1 \
  || docker build -t cdlbib-ci-linux -f "$here/Dockerfile" "$repo"

checkout=$(mktemp -d "${TMPDIR:-/tmp}/cdlbib-ci-linux.XXXXXX")
trap 'rm -rf "$checkout"' EXIT
git clone -q --depth 1 "file://$repo" "$checkout/repo"
if [ "$dirty" = yes ]; then
  (cd "$repo" && git ls-files -z --modified --others --exclude-standard) | while IFS= read -r -d '' name; do
    if [ -e "$repo/$name" ]; then
      mkdir -p "$checkout/repo/$(dirname "$name")" && cp -p "$repo/$name" "$checkout/repo/$name"
    else
      rm -f "$checkout/repo/$name"
    fi
  done
fi

# The checkout is copied inside, so that the user there owns it and nothing here is written.
docker run --rm --cpus "$cpus" -e CI=true "${options[@]}" -v "$checkout/repo:/checkout:ro" cdlbib-ci-linux \
  bash -c '
    set -eu
    export PATH="/opt/python/'"$python"'/bin:$PATH"
    cp -a /checkout "$HOME/repo" && cd "$HOME/repo"
    export CROSSREF_MAILTO="$(cat .github/actions/crossref-contact/mailto.txt)"
    python -m pip install -q --no-warn-script-location ".[research,pdf,tui]" >/dev/null
    exec "$@"' ci "$@"
