#!/bin/sh
# Install the cdlbib command on macOS or Linux, whatever the default Python is.
#
#   sh install.sh                       (from a checkout of the repository)
#   curl -LsSf https://raw.githubusercontent.com/ContextLab/CDL-bibliography/master/install.sh | sh
#   curl -LsSf https://raw.githubusercontent.com/ContextLab/CDL-bibliography/master/install.sh | sh -s -- --extras tui
#
# cdlbib needs Python 3.11 or later. The script installs it with `uv tool install`, into an
# environment of its own:
#   - uv is used where it is found (version 0.5.0 or later);
#   - when uv is missing (or older), the script says so and downloads uv with uv's own
#     installer (https://astral.sh/uv/install.sh) into a folder of its own;
#   - when no Python 3.11 or later is installed, uv downloads one into uv's own folder.
#     The Python already on the computer and the default `python` are not changed.
# With --no-uv nothing but the package is downloaded: an installed uv is used, else a
# virtual environment is made with the newest Python 3.11+ on PATH.
# Running it again upgrades or repairs the installation in place.
#
# It never uses sudo, never edits a shell profile, and writes only to:
#   ${XDG_DATA_HOME:-$HOME/.local/share}/cdlbib/   install-state, uv/ (a downloaded uv),
#                                                  venv/ (--no-uv without uv)
#   ${XDG_BIN_HOME:-$HOME/.local/bin}/             links to the commands (--no-uv without uv)
#   the folders of uv: `uv tool dir`, `uv tool dir --bin`, `uv python dir`, `uv cache dir`
#   a temporary folder, removed when the script ends
#
# The folder the script is started in is never a source of programs or settings: PATH
# entries that are not absolute folders, that folder and the checkout are not searched;
# every program is run by its full path; uv, pip and Python run in a fresh temporary
# folder, uv with --no-config and Python with -I. A checkout is the source only when this
# script is a file in it; read from a pipe, the source is the repository.
# Run with --help for the options.

set -eu

PACKAGE=cdlbib
REPOSITORY=https://github.com/ContextLab/CDL-bibliography
UV_INSTALLER=https://astral.sh/uv/install.sh
UV_MINIMUM=0.5.0    # the first uv whose installer takes UV_UNMANAGED_INSTALL; `uv tool install`
                    # has --with, --force and --reinstall-package, and `uv tool dir` has --bin
PYTHON_REQUEST='>=3.11'

usage() {
    cat <<'EOF'
Install the cdlbib command (macOS and Linux). cdlbib needs Python 3.11 or later; this
script installs it into an environment of its own, so the default Python does not matter.

Usage: sh install.sh [options]
       curl -LsSf https://raw.githubusercontent.com/ContextLab/CDL-bibliography/master/install.sh | sh -s -- [options]

Options:
  --extras LIST   optional extras to install now, comma-separated: research,pdf,tui
                  (default: none; cdlbib installs each one the first time it is needed)
  --ref REF       install this branch, tag or commit of the GitHub repository
  --repo URL      install from this https git repository instead of
                  https://github.com/ContextLab/CDL-bibliography
  --pypi          install cdlbib from PyPI instead of from GitHub or the checkout
  --ask           ask before installing and before downloading uv; without a terminal,
                  install nothing and print the commands instead
  --no-uv         never download uv: use an installed uv, else a Python 3.11+ on PATH,
                  else print what to install
  --uninstall     remove what this script installed
  --help          show this text

Source: the checkout this script sits in (when run as a file from one and none of
--ref, --repo and --pypi is given); otherwise the GitHub repository; with --pypi, PyPI.

How: with `uv tool install`. A uv on PATH (0.5.0 or later) is used; when there is none,
the script says so and downloads uv with its installer (https://astral.sh/uv/install.sh)
into ${XDG_DATA_HOME:-$HOME/.local/share}/cdlbib/uv. When no Python 3.11 or later is
installed, uv downloads one into its own folder; the default python is not changed.
With --no-uv and no uv, a virtual environment is made in
${XDG_DATA_HOME:-$HOME/.local/share}/cdlbib/venv with the newest Python 3.11+ on PATH,
with links in ${XDG_BIN_HOME:-$HOME/.local/bin}.

Running the script again upgrades or repairs the installation in place. It never uses
sudo and never edits a shell profile.
EOF
}

say() { printf '%s\n' "$*"; }
warn() { printf '%s\n' "$*" >&2; }
die() { warn "install.sh: $*"; exit 1; }

# The physical path of a folder (links and ".." resolved); fails when it cannot be entered.
physical() {
    (CDPATH='' cd -P -- "$1" 2>/dev/null && pwd -P)
}

# A new PATH, for this script and for every program it runs: the physical paths of the
# entries of the given PATH that could be resolved. An entry is left out when it is not an
# absolute path ("", ".", a relative name), when it cannot be entered, or when it is, after
# resolving links and "..", the folder the script was started in or the checkout. Whatever
# cannot be decided is left out. Only shell builtins are used here.
safe_path() {
    kept=""
    old_ifs=$IFS
    set -f
    IFS=:
    for entry in $user_path; do
        case $entry in
            /*) ;;
            *) continue ;;
        esac
        real=$(physical "$entry") || continue
        case $real in
            /*) ;;
            *) continue ;;
        esac
        if [ "$real" = "$started_in" ] || [ "$real" = "$checkout" ]; then
            continue
        fi
        case ":$kept:" in
            *":$real:"*) continue ;;
        esac
        case $real in
            *:*) continue ;;
        esac
        kept="$kept${kept:+:}$real"
    done
    IFS=$old_ifs
    set +f
    PATH=$kept
    export PATH
    hash -r 2>/dev/null || true
}

usable_path() {
    [ -n "$PATH" ] || die "no folder of PATH can be used: entries that are not absolute paths, that cannot be entered, the folder the script is started in and the checkout are not searched."
}

# The full path of a program on PATH. Fails (the program counts as not installed) when
# the answer is not the absolute path of an executable file, or when its folder is, or
# cannot be shown not to be, the folder the script was started in or the checkout.
program() {
    found=$(command -v "$1" 2>/dev/null) || return 1
    case $found in
        /*) ;;
        *) return 1 ;;
    esac
    if [ ! -f "$found" ] || [ ! -x "$found" ]; then
        return 1
    fi
    where=$(physical "${found%/*}/") || return 1
    if [ "$where" = "$started_in" ] || [ "$where" = "$checkout" ]; then
        return 1
    fi
    printf '%s\n' "$found"
}

# A path as the path of a file:// address: every byte that is not a letter, a digit or one
# of . _ ~ / - is written as %XX, so nothing in it can be read as part of a requirement.
url_path() {
    case $1 in
        *[!A-Za-z0-9._~/-]*) ;;
        *) printf '%s\n' "$1"; return 0 ;;
    esac
    encoded=""
    for byte in $(printf '%s' "$1" | od -An -v -tx1); do
        case $byte in
            2d|2e|2f|5f|7e|3[0-9]|4[1-9a-f]|5[0-9a]|6[1-9a-f]|7[0-9a])
                # shellcheck disable=SC2059
                encoded="$encoded$(printf "\\$(printf '%03o' "0x$byte")")" ;;
            *) encoded="$encoded%$byte" ;;
        esac
    done
    printf '%s\n' "$encoded"
}

# Is the file $1 the pyproject.toml of this package? (Read with the shell itself.)
is_package() {
    [ -f "$1" ] || return 1
    while IFS= read -r text || [ -n "$text" ]; do
        case $text in
            'name = "cdlbib"') return 0 ;;
        esac
    done <"$1"
    return 1
}

# One line that a person can paste into a shell: the arguments, quoted where needed.
quoted() {
    line=""
    for word in "$@"; do
        case $word in
            ''|*[!A-Za-z0-9_./:@+,-]*)
                word=\'$(printf '%s' "$word" | sed "s/'/'\\\\''/g")\' ;;
        esac
        line="$line${line:+ }$word"
    done
    printf '%s\n' "$line"
}

# Print a command, then run it (with --ask and no terminal: print only).
run() {
    say "+ $(quoted "$@")"
    [ "$dry" = 1 ] || "$@"
}

# With --ask: a yes/no question on the terminal. Without --ask: yes.
confirm() {
    [ "$ask" = 1 ] || return 0
    [ "$dry" = 1 ] && return 0
    printf '%s [y/N] ' "$1" >&2
    if [ -t 0 ]; then
        read -r reply || reply=""
    else
        read -r reply </dev/tty || reply=""
    fi
    case $reply in
        y|Y|yes|Yes|YES) return 0 ;;
    esac
    die "stopped: nothing was installed."
}

has_terminal() {
    [ -t 0 ] && return 0
    # shellcheck disable=SC2188
    (: </dev/tty) 2>/dev/null
}

# On macOS /usr/bin/python3 and /usr/bin/git are placeholders that open an "install the
# developer tools" window when those tools are absent; they are used only when present.
usable() {
    case $1 in
        /usr/bin/*)
            if [ "$os" = Darwin ] && ! xcode-select -p >/dev/null 2>&1; then
                return 1
            fi ;;
    esac
    return 0
}

# Is the uv program $1 at least UV_MINIMUM?
uv_new_enough() {
    numbers=$("$1" --version 2>/dev/null | sed -n 's/^uv \([0-9][0-9]*\)\.\([0-9][0-9]*\)\..*/\1 \2/p' | sed -n 1p)
    case $numbers in
        ''|*[!0-9\ ]*) return 1 ;;
    esac
    major=${numbers% *}
    minor=${numbers#* }
    [ "$major" -gt 0 ] || [ "$minor" -ge 5 ]
}

# The newest released Python 3.11+ on PATH (the version is asked of the program, not read
# from its name), in $python; fails when there is none.
find_python() {
    python=""
    best=0
    for name in python3.14 python3.13 python3.12 python3.11 python3 python; do
        candidate=$(program "$name") || continue
        usable "$candidate" || continue
        minor=$("$candidate" -I -B -c 'import sys
v = sys.version_info
print(v[1] if v[0] == 3 and v[1] >= 11 and v.releaselevel == "final" else 0)' 2>/dev/null) || continue
        case $minor in
            ''|*[!0-9]*) continue ;;
        esac
        if [ "$minor" -gt "$best" ]; then
            best=$minor
            python=$candidate
        fi
    done
    [ -n "$python" ]
}

# Can $python make a virtual environment with pip in it? (Debian and Ubuntu keep that in
# the separate package python3-venv.)
can_venv() {
    "$python" -I -B -c 'import venv, ensurepip' >/dev/null 2>&1
}

need_git() {
    [ "$source" = git ] || return 0
    git=$(program git) || git=""
    if [ -z "$git" ] || ! usable "$git"; then
        warn "install.sh: git is needed to install from $REPOSITORY and was not found."
        warn "Install git (macOS: xcode-select --install; Debian/Ubuntu: apt-get install git;"
        warn "Fedora: dnf install git), then run this script again."
        exit 1
    fi
}

# Save an https address to a file, with curl or wget.
download() {
    case $1 in
        https://*) ;;
        *) die "refusing to download $1: not an https address." ;;
    esac
    if [ -n "$curl" ]; then
        run "$curl" --proto '=https' --tlsv1.2 -fsSL -o "$2" "$1"
    else
        run "$wget" --https-only -q -O "$2" "$1"
    fi
}

state_value() {
    [ -f "$state" ] || return 0
    sed -n "s/^$1=//p" "$state" | sed -n 1p
}

path_line() {
    case ":$user_path:" in
        *":$1:"*) return 0 ;;
    esac
    shown=$1
    case $1 in
        "$HOME"/*) shown="\$HOME${1#"$HOME"}" ;;
    esac
    say ""
    say "$1 is not on your PATH."
    case $(basename "${SHELL:-sh}") in
        zsh)
            say "Add this line to ~/.zshrc, then open a new terminal:"
            say "  export PATH=\"$shown:\$PATH\"" ;;
        bash)
            if [ "$os" = Darwin ]; then profile=.bash_profile; else profile=.bashrc; fi
            say "Add this line to ~/$profile, then open a new terminal:"
            say "  export PATH=\"$shown:\$PATH\"" ;;
        fish)
            say "Run this once in fish, then open a new terminal:"
            say "  fish_add_path \"$shown\"" ;;
        *)
            say "Add this line to ~/.profile, then log in again:"
            say "  export PATH=\"$shown:\$PATH\"" ;;
    esac
}

# The console commands of the installed package, one per line.
console_scripts() {
    "$1" -I -c 'from importlib.metadata import distribution
for entry in distribution("cdlbib").entry_points:
    if entry.group == "console_scripts":
        print(entry.name)'
}

remove_venv_install() {
    old_bin=$(state_value bin)
    for link in "${old_bin:-$bin_dir}"/*; do
        [ -L "$link" ] || continue
        case $(readlink "$link") in
            "$venv/bin/"*) run rm -f "$link" ;;
        esac
    done
    if [ -d "$venv" ]; then
        run rm -rf "$venv"
    fi
}

# Remove an installation this script made (recorded in the state file), and only that.
remove_installed() {
    case $(state_value method) in
        uv)
            old_uv=$(state_value uv)
            case $old_uv in
                /*) [ -x "$old_uv" ] || old_uv="" ;;
                *) old_uv="" ;;
            esac
            [ -n "$old_uv" ] || old_uv=$(program uv) || old_uv=""
            if [ -z "$old_uv" ]; then
                warn "install.sh: uv was not found, so its $PACKAGE tool was left in place."
            elif "$old_uv" --no-config tool list 2>/dev/null | grep -q "^$PACKAGE "; then
                run "$old_uv" --no-config tool uninstall "$PACKAGE" || warn "install.sh: uv did not uninstall $PACKAGE."
            fi ;;
        venv)
            remove_venv_install ;;
        *)
            return 1 ;;
    esac
    rm -f "$state"
    return 0
}

uninstall() {
    removed=0
    if remove_installed; then
        removed=1
    fi
    if [ -d "$own_uv_dir" ]; then
        run rm -rf "$own_uv_dir"
        removed=1
        say "The uv that this script downloaded is removed. Pythons and cached files that uv"
        say "downloaded stay in uv's own folders (${XDG_DATA_HOME:-$HOME/.local/share}/uv and ${XDG_CACHE_HOME:-$HOME/.cache}/uv)."
    fi
    rmdir "$home_dir" 2>/dev/null || true
    if [ "$removed" = 1 ]; then
        say "Removed $PACKAGE."
    else
        say "Nothing to remove: this script has no installation of $PACKAGE here."
    fi
}

install_uv() {
    curl=$(program curl) || curl=""
    wget=$(program wget) || wget=""
    shell=$(program sh) || die "sh was not found on PATH."
    env=$(program env) || die "env was not found on PATH."
    if [ -z "$curl$wget" ]; then
        warn "install.sh: uv has to be downloaded, and neither curl nor wget is installed."
        warn "Nothing was installed. Install curl or wget, or uv itself"
        warn "(https://docs.astral.sh/uv/getting-started/installation/), then run this script again."
        exit 1
    fi
    if [ -z "$curl" ] && ! "$wget" --help 2>&1 | grep -q -e '--https-only'; then
        die "this wget cannot be limited to https. Install curl, then run this script again."
    fi
    say "$1: downloading uv with its installer ($UV_INSTALLER, saved to a temporary file and run with sh) into $own_uv_dir; no shell profile is changed."
    confirm "Download and run the uv installer?"
    download "$UV_INSTALLER" "$tmp/uv-install.sh"
    run "$env" UV_UNMANAGED_INSTALL="$own_uv_dir" "$shell" "$tmp/uv-install.sh"
    uv=$own_uv_dir/uv
    if [ "$dry" != 1 ] && ! uv_new_enough "$uv"; then
        die "the uv installer did not leave a working uv in $own_uv_dir."
    fi
}

uv_tool_install() {
    # --force replaces commands that are already there (an earlier or interrupted run);
    # --reinstall-package builds cdlbib again from the source, so a changed checkout or
    # branch is picked up, while the other packages are only brought up to date.
    # pip goes into the environment so that cdlbib can install an optional extra later,
    # also when uv is not on PATH. --no-config: no uv.toml or pyproject.toml of any folder
    # (or of the user) changes what is installed or from where; uv's environment variables
    # still apply.
    uv_spec=$spec
    if [ "$source" = local ]; then
        case $checkout in
            *[!A-Za-z0-9._~/-]*)
                # uv cannot read a requirement whose address has such a character, however
                # it is written. The checkout is reached through a link with a fixed name in
                # the temporary folder, which is the folder uv runs in.
                say "The path of the checkout has characters that uv does not take in a requirement: it is installed through a link in the temporary folder. (\`uv tool upgrade\` will not find it later; run this script again to upgrade.)"
                [ "$dry" = 1 ] || rm -f "$tmp/src"
                run ln -s "$checkout" "$tmp/src"
                uv_spec=./src$bracket ;;
        esac
    fi
    run "$uv" --no-config tool install --python "$PYTHON_REQUEST" --with pip --force \
        --reinstall-package "$PACKAGE" -- "$uv_spec"
}

main() {
    ask=0
    dry=0
    no_uv=0
    pypi=0
    ref=""
    repo=""
    extras=""
    action=install
    tmp=""
    checkout=""
    user_path=${PATH:-}
    started_in=$(pwd -P 2>/dev/null) || started_in=""
    case $started_in in
        /*) ;;
        *) die "the current folder could not be determined; start the script from a folder that exists." ;;
    esac
    safe_path
    usable_path

    while [ $# -gt 0 ]; do
        case $1 in
            --help|-h) usage; exit 0 ;;
            --ask) ask=1 ;;
            --no-uv) no_uv=1 ;;
            --pypi) pypi=1 ;;
            --uninstall) action=uninstall ;;
            --extras|--ref|--repo)
                [ $# -ge 2 ] || die "$1 needs a value. See --help."
                case $1 in
                    --extras) extras=$2 ;;
                    --ref) ref=$2 ;;
                    --repo) repo=$2 ;;
                esac
                shift ;;
            --extras=*) extras=${1#--extras=} ;;
            --ref=*) ref=${1#--ref=} ;;
            --repo=*) repo=${1#--repo=} ;;
            *) die "unknown option: $1. See --help." ;;
        esac
        shift
    done
    # Only these three extras, and only names for --ref and --repo that cannot be read as
    # anything else inside a requirement or on a command line.
    old_ifs=$IFS
    set -f
    IFS=,
    for extra in $extras; do
        case $extra in
            research|pdf|tui) ;;
            *) IFS=$old_ifs; die "--extras takes research, pdf and tui, separated by commas (got: $extras)." ;;
        esac
    done
    IFS=$old_ifs
    set +f
    case $extras in
        ,*|*,|*,,*) die "--extras takes research, pdf and tui, separated by commas (got: $extras)." ;;
    esac
    case $ref in
        -*|*..*|*[!A-Za-z0-9._/-]*) die "--ref takes a branch, tag or commit name: letters, digits and . _ / - (not starting with -, without ..)." ;;
    esac
    case $repo in
        '') ;;
        *..*|*[!A-Za-z0-9._/:~-]*) die "--repo takes the https address of a git repository." ;;
        https://[A-Za-z0-9]*) REPOSITORY=$repo ;;
        *) die "--repo takes the https address of a git repository." ;;
    esac
    if [ "$pypi" = 1 ] && [ -n "$ref$repo" ]; then
        die "--pypi cannot be used together with --ref or --repo."
    fi

    os=$(uname -s 2>/dev/null) || os=unknown
    case $os in
        Darwin|Linux) ;;
        *)
            case $os in
                MINGW*|MSYS*|CYGWIN*|Windows*) warn "install.sh: Windows is not supported by this script." ;;
                *) warn "install.sh: this script supports macOS and Linux, not $os." ;;
            esac
            warn "Install by hand with uv (https://docs.astral.sh/uv/):"
            warn "  uv tool install --python \"$PYTHON_REQUEST\" \"cdlbib @ git+$REPOSITORY\""
            warn "or with Python 3.11 or later:"
            warn "  python -m pip install \"cdlbib @ git+$REPOSITORY\""
            exit 1 ;;
    esac

    case ${HOME:-} in
        /*) ;;
        *) die "HOME is not set to a folder, so there is nowhere to install." ;;
    esac
    data_dir=${XDG_DATA_HOME:-$HOME/.local/share}
    bin_dir=${XDG_BIN_HOME:-$HOME/.local/bin}
    case $data_dir in /*) ;; *) data_dir=$HOME/.local/share ;; esac
    case $bin_dir in /*) ;; *) bin_dir=$HOME/.local/bin ;; esac
    home_dir=$data_dir/$PACKAGE
    venv=$home_dir/venv
    own_uv_dir=$home_dir/uv
    state=$home_dir/install-state

    trap 'if [ -n "$tmp" ] && [ "$dry" != 1 ]; then rm -rf "$tmp"; fi' EXIT
    trap 'exit 130' INT
    trap 'exit 143' TERM HUP

    # What to install. A checkout is the source only when this script is a file named
    # install.sh and the folder that file is in (its physical path) holds the package's
    # pyproject.toml. The folder the script was started in is never looked at: a script
    # read from a pipe has no file, so its source is the repository.
    case $0 in
        */install.sh) script_dir=${0%/*} ;;
        install.sh) script_dir=. ;;
        *) script_dir="" ;;
    esac
    if [ -n "$script_dir" ] && [ -f "$0" ]; then
        checkout=$(CDPATH='' cd -P -- "${script_dir:-/}" 2>/dev/null && pwd -P) || checkout=""
        if ! is_package "$checkout/pyproject.toml"; then
            checkout=""
        fi
    fi
    safe_path
    usable_path
    # Everything from here on is named by its full path and runs outside the folder the
    # script was started in, so that no file there (pyproject.toml, uv.toml, .python-version,
    # pip.conf, setup.cfg, sitecustomize.py) can steer uv, pip or Python.
    cd /
    for name in sed grep mkdir rm mktemp; do
        program "$name" >/dev/null || die "$name was not found on PATH (${PATH:-empty}). Folders that are not absolute paths, the folder the script is started in and the checkout are not searched."
    done

    if [ "$action" = uninstall ]; then
        uninstall
        exit 0
    fi

    bracket=${extras:+[$extras]}
    if [ "$pypi" = 1 ]; then
        source=pypi
        spec=$PACKAGE$bracket
        from="PyPI"
    elif [ -n "$checkout" ] && [ -z "$ref$repo" ]; then
        source=local
        # The checkout is named by a file:// address, never by its path inside the
        # requirement: a path with a space, #, @, ; or [ cannot be read as something else.
        spec="$PACKAGE$bracket @ file://$(url_path "$checkout")"
        from="the checkout $checkout"
    else
        source=git
        spec="$PACKAGE$bracket @ git+$REPOSITORY${ref:+@$ref}"
        from="$REPOSITORY${ref:+ ($ref)}"
    fi

    if [ "$ask" = 1 ] && ! has_terminal; then
        dry=1
        say "--ask was given and there is no terminal to ask on: nothing is installed."
        say "These are the commands that would run:"
    fi

    # How to install it: with a uv that is already here, else with a downloaded one;
    # with --no-uv, with a uv that is already here, else in a virtual environment.
    uv=""
    method=uv
    why="uv was not found"
    path_uv=$(program uv) || path_uv=""
    if [ -n "$path_uv" ]; then
        if uv_new_enough "$path_uv"; then
            uv=$path_uv
        else
            why="$path_uv is older than uv $UV_MINIMUM and is left as it is"
        fi
    fi
    if [ -z "$uv" ] && [ -x "$own_uv_dir/uv" ] && uv_new_enough "$own_uv_dir/uv"; then
        uv=$own_uv_dir/uv
    fi
    if [ -z "$uv" ] && [ "$no_uv" = 1 ]; then
        if find_python && can_venv; then
            method=venv
        else
            warn "install.sh: $why, --no-uv was given, and"
            if [ -n "$python" ]; then
                warn "$python cannot make a virtual environment (its venv module or ensurepip is missing)."
            else
                warn "no Python 3.11 or later was found on PATH."
            fi
            warn "Nothing was installed. Install one of these, then run this script again:"
            warn "  uv $UV_MINIMUM or later (https://docs.astral.sh/uv/getting-started/installation/;"
            warn "    an installed uv is updated with: uv self update)"
            warn "  Python 3.11 or later with its venv module (macOS: https://www.python.org/downloads/"
            warn "    or brew install python; Debian/Ubuntu: apt-get install python3 python3-venv)"
            warn "or run the script without --no-uv, which downloads uv."
            exit 1
        fi
    fi

    need_git
    say "Installing $PACKAGE from $from."
    # One temporary folder for the script and for the programs it runs (uv, pip and uv's
    # installer leave files in TMPDIR); it is removed when the script ends.
    if [ "$dry" = 1 ]; then
        tmp=${TMPDIR:-/tmp}/cdlbib-install.XXXXXX
    else
        tmp=$(mktemp -d "${TMPDIR:-/tmp}/cdlbib-install.XXXXXX")
        chmod 700 "$tmp"
        TMPDIR=$tmp
        export TMPDIR
        cd "$tmp"
    fi
    if [ -z "$uv" ] && [ "$method" = uv ]; then
        install_uv "$why"
    fi
    confirm "Install $PACKAGE with $method?"

    # An earlier installation by the other route is removed first, so only one is left.
    previous=$(state_value method)
    if [ "$dry" != 1 ] && [ -n "$previous" ] && [ "$previous" != "$method" ]; then
        say "Replacing the earlier installation (made with $previous)."
        remove_installed || true
    fi

    # Recorded before the work starts, so that --uninstall also removes an unfinished one.
    if [ "$dry" != 1 ]; then
        if [ "$method" = uv ]; then command_dir=$("$uv" --no-config tool dir --bin); else command_dir=$bin_dir; fi
        mkdir -p "$home_dir"
        {
            say "method=$method"
            say "bin=$command_dir"
            if [ "$method" = uv ]; then say "uv=$uv"; fi
        } >"$state"
    fi

    case $method in
        uv)
            if [ "$dry" != 1 ] && ! "$uv" --no-config python find "$PYTHON_REQUEST" >/dev/null 2>&1; then
                say "No Python 3.11 or later was found: uv downloads one into its own folder ($("$uv" --no-config python dir)); the default python is not changed."
            fi
            # An environment that does not work (an interrupted run, deleted files) is
            # removed first, so that the result is the same as a first installation.
            tools=$("$uv" --no-config tool dir 2>/dev/null) || tools=""
            case $tools in
                /*)
                    if [ "$dry" != 1 ] && [ -e "$tools/$PACKAGE" ] && ! "$tools/$PACKAGE/bin/python" -I -c 'import pip, cdlbib' >/dev/null 2>&1; then
                        say "The $PACKAGE tool in $tools is incomplete: it is removed and installed again."
                        "$uv" --no-config tool uninstall "$PACKAGE" >/dev/null 2>&1 || true
                        rm -rf "${tools:?}/$PACKAGE"
                    fi ;;
            esac
            if ! uv_tool_install; then
                # What an interrupted run left behind can stop uv; start from nothing, once.
                say "Trying again after removing the unfinished $PACKAGE tool."
                "$uv" --no-config tool uninstall "$PACKAGE" >/dev/null 2>&1 || true
                tools=$("$uv" --no-config tool dir)
                case $tools in
                    /*) rm -rf "${tools:?}/$PACKAGE" ;;
                esac
                uv_tool_install
            fi ;;
        venv)
            if [ "$dry" != 1 ] && [ -d "$venv" ] && ! "$venv/bin/python" -I -c 'import sys, pip
raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
                # Not a working environment (an interrupted run, or its Python is gone).
                run rm -rf "$venv"
            fi
            if [ ! -x "$venv/bin/python" ]; then
                run mkdir -p "$home_dir"
                if ! run "$python" -I -m venv "$venv"; then
                    # A Python that is reached through a link in another folder can fail
                    # here; the program the link leads to is tried once.
                    rm -rf "$venv"
                    real=$("$python" -I -B -c 'import os, sys
print(os.path.realpath(sys.executable))')
                    run "$real" -I -m venv "$venv"
                fi
            fi
            run "$venv/bin/python" -I -m pip install --disable-pip-version-check --upgrade -- "$spec"
            run mkdir -p "$bin_dir"
            if [ "$dry" = 1 ]; then
                say "+ ln -sf $(quoted "$venv/bin/$PACKAGE") $(quoted "$bin_dir/$PACKAGE")   (and each other command of the package)"
            else
                for name in $(console_scripts "$venv/bin/python"); do
                    if [ -e "$bin_dir/$name" ] && [ ! -L "$bin_dir/$name" ]; then
                        die "$bin_dir/$name exists and is not a link; it was left alone. Move it away, then run this script again."
                    fi
                    run ln -sf "$venv/bin/$name" "$bin_dir/$name"
                done
            fi ;;
    esac

    if [ "$dry" = 1 ]; then
        say "Nothing was installed. Run the script without --ask, or in a terminal, to install."
        exit 1
    fi

    version=$("$command_dir/$PACKAGE" --version) || die "$command_dir/$PACKAGE was installed but '$PACKAGE --version' failed."
    say ""
    say "Installed: $version"
    say "Command:   $command_dir/$PACKAGE (installed with $method)"
    path_line "$command_dir"
}

main "$@"
