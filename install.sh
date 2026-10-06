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
#   - when uv is missing (or older), the script says so and downloads one pinned version of
#     uv with uv's own installer (https://astral.sh/uv/VERSION/install.sh) into a folder of
#     its own. The installer is run only when its SHA-256 is the one written in this script
#     (see UV_VERSION below); the installer in turn carries the SHA-256 of the archive of uv
#     for each platform and compares the archive it downloads before unpacking it;
#   - the environment is made with a Python 3.11, 3.12 or 3.13 (the versions the package is
#     tested on); when none is installed, uv downloads one into uv's own folder.
#     The Python already on the computer and the default `python` are not changed.
# With --no-uv nothing but the package is downloaded: an installed uv is used, else a
# virtual environment is made with the newest Python from 3.11 to 3.13 on PATH.
# Running it again upgrades or repairs the installation. A command that runs is left as it
# is until the new version has been installed beside it and has run; only an installation
# whose command does not run is removed first.
#
# It never uses sudo, never edits a shell profile, and writes only to:
#   ${XDG_DATA_HOME:-$HOME/.local/share}/cdlbib/   install-state (what was installed, where,
#                                                  and with which uv), uv/ (a downloaded uv),
#                                                  dist/ (the wheel built from a checkout),
#                                                  venv/ (--no-uv without uv)
#   the checkout, when it is the source: build/ and src/cdlbib.egg-info/ (the build's own)
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

# The folders uv names are read from its output. With colour forced in the environment
# (FORCE_COLOR, CLICOLOR_FORCE) uv writes colour codes into them, so colour is off here.
unset FORCE_COLOR CLICOLOR_FORCE
NO_COLOR=1
export NO_COLOR

PACKAGE=cdlbib
REPOSITORY=https://github.com/ContextLab/CDL-bibliography

# ---- THE uv THAT THIS SCRIPT DOWNLOADS: the one place to change -------------------------
# Used only when no uv (0.5.0 or later) is installed. The installer of exactly this version
# is downloaded, and it is run only when its SHA-256 is the one below. To move to another
# version of uv:
#   1. read the release notes and the new installer (https://astral.sh/uv/NEW/install.sh);
#      it must still honour UV_UNMANAGED_INSTALL and UV_NO_MODIFY_PATH, and still compare
#      the archive it downloads with a checksum it carries (its verify_checksum);
#   2. set UV_VERSION, and set UV_INSTALLER_SHA256 to what this prints (on Linux: sha256sum
#      in place of shasum -a 256):
#        curl --proto '=https' --tlsv1.2 -fsSL https://astral.sh/uv/NEW/install.sh | shasum -a 256
#   3. run: CDLBIB_TEST_INSTALL_UV_DOWNLOAD=1 python -m pytest tests/test_install_script.py
UV_VERSION=0.12.23
UV_INSTALLER_SHA256=b8e6c43099ee9f9a550984d3ad56948457c689e7a99c090b35377234ac241491
# -----------------------------------------------------------------------------------------
UV_INSTALLER=https://astral.sh/uv/$UV_VERSION/install.sh
UV_MANUAL=https://docs.astral.sh/uv/getting-started/installation/
UV_MINIMUM=0.5.0    # the first uv whose installer takes UV_UNMANAGED_INSTALL; `uv tool install`
                    # has --with, --force and --reinstall-package, and `uv tool dir` has --bin
PYTHON_REQUEST='>=3.11,<3.14'    # the versions the package's tests run on

usage() {
    sed "s/UV_VERSION_HERE/$UV_VERSION/g" <<'EOF'
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
  --no-uv         never download uv: use an installed uv, else a Python 3.11 to 3.13 on PATH,
                  else print what to install
  --uninstall     remove what this script installed
  --help          show this text

Source: the checkout this script sits in (when run as a file from one and none of
--ref, --repo and --pypi is given); otherwise the GitHub repository; with --pypi, PyPI.

How: with `uv tool install`. A uv on PATH (0.5.0 or later) is used as it is; when there
is none, the script says so and downloads uv UV_VERSION_HERE with its installer
(https://astral.sh/uv/UV_VERSION_HERE/install.sh) into
${XDG_DATA_HOME:-$HOME/.local/share}/cdlbib/uv. The environment is made with a
Python 3.11, 3.12 or 3.13; when none is installed, uv downloads one into its own folder.
The default python is not changed.

What is checked when uv is downloaded:
  - the installer: its SHA-256 must be the one written in this script for that version
    (UV_INSTALLER_SHA256). Otherwise it is not run and nothing is installed.
  - the archive of uv: the installer carries the SHA-256 of the archive for each platform
    and compares the archive it downloads before unpacking it. It skips that comparison
    when there is no sha256sum command, so this script gives it one (made from sha256sum,
    shasum or openssl, whichever is installed) and installs nothing when none is found.
  - the uv that results must report version UV_VERSION_HERE.
Not checked: signatures (none is verified; the SHA-256 in this script was read from
astral.sh when the version was chosen), a uv that is already installed, and the Python
and the packages that uv downloads (uv applies its own checks to those).
With --no-uv and no uv, a virtual environment is made in
${XDG_DATA_HOME:-$HOME/.local/share}/cdlbib/venv with the newest Python from 3.11 to 3.13 on PATH,
with links in ${XDG_BIN_HOME:-$HOME/.local/bin}.

Running the script again upgrades or repairs the installation. While the installed
command runs, it is kept until the new version has been installed beside it (in a
temporary folder) and has run there; when the new version cannot be installed, the script
stops with an error and the old command still works. An installation whose command does
not run is removed and installed again.

--uninstall removes the installation recorded in
${XDG_DATA_HOME:-$HOME/.local/share}/cdlbib/install-state (uv's tool directory, the folder
of the commands, and the uv that was used), whatever UV_TOOL_DIR is now. When that cannot
be done (no uv, or uv fails), nothing else is removed, the record is kept and the script
ends with an error that says what to do.

It never uses sudo and never edits a shell profile.
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

# Is "MAJOR MINOR" at least UV_MINIMUM (0.5)? Anything that is not two numbers is not.
new_enough() {
    case $1 in
        *[!0-9\ ]*) return 1 ;;
        [0-9]*\ [0-9]*) ;;
        *) return 1 ;;
    esac
    major=${1% *}
    minor=${1#* }
    case $major$minor in
        *\ *) return 1 ;;
    esac
    [ "$major" -gt 0 ] || [ "$minor" -ge 5 ]
}

# Is the uv program $1 at least UV_MINIMUM?
uv_new_enough() {
    new_enough "$("$1" --version 2>/dev/null | sed -n 's/^uv \([0-9][0-9]*\)\.\([0-9][0-9]*\)\..*/\1 \2/p' | sed -n 1p)"
}

# Is the file $1 the installer of a uv that is at least UV_MINIMUM, and does it know the
# variable that keeps it out of shell profiles? (Older installers ignore that variable,
# install into ~/.cargo/bin and edit the profiles.)
installer_new_enough() {
    new_enough "$(sed -n 's/^APP_VERSION="\([0-9][0-9]*\)\.\([0-9][0-9]*\)\..*/\1 \2/p' "$1" | sed -n 1p)" || return 1
    grep -q 'UV_UNMANAGED_INSTALL' "$1"
}

# The newest released Python 3.11 to 3.13 on PATH (the version is asked of the program, not read
# from its name), in $python; fails when there is none.
find_python() {
    python=""
    best=0
    for name in python3.13 python3.12 python3.11 python3 python; do
        candidate=$(program "$name") || continue
        usable "$candidate" || continue
        minor=$("$candidate" -I -B -c 'import sys
v = sys.version_info
print(v[1] if v[0] == 3 and 11 <= v[1] <= 13 and v.releaselevel == "final" else 0)' 2>/dev/null) || continue
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

# Remove the links in the folder $1 that lead into $2 (a path that ends with a slash).
remove_links() {
    for link in "$1"/*; do
        [ -L "$link" ] || continue
        case $(readlink "$link") in
            "$2"*) run rm -f "$link" || return 1 ;;
        esac
    done
    return 0
}

# What the state file records, read into rec_*. It can hold two installations at once (one
# made with uv, one in the virtual environment) while one is replacing the other.
#   method=uv|venv   the route of the latest run        bin=      the folder of its commands
#   uv=              the uv that installed the tool     tool_dir= uv's tool directory then
#   tool_bin=        the folder uv put the commands in  venv_bin= the folder of the links to
#                                                                 the virtual environment
# A file of an earlier version of this script has only method, bin and uv: the tool
# directory is then read from where the command link leads, and is unknown without it.
read_state() {
    rec_method=$(state_value method)
    rec_uv=$(state_value uv)
    rec_tool_dir=$(state_value tool_dir)
    rec_tool_bin=$(state_value tool_bin)
    rec_venv_bin=$(state_value venv_bin)
    has_uv=0
    has_venv=0
    if [ -n "$rec_tool_dir$rec_tool_bin" ]; then
        has_uv=1
    elif [ "$rec_method" = uv ]; then
        has_uv=1
        rec_tool_bin=$(state_value bin)
        if [ -L "$rec_tool_bin/$PACKAGE" ]; then
            target=$(readlink "$rec_tool_bin/$PACKAGE") || target=""
            case $target in
                /*/"$PACKAGE"/bin/"$PACKAGE") rec_tool_dir=${target%/"$PACKAGE"/bin/"$PACKAGE"} ;;
            esac
        fi
    fi
    if [ -n "$rec_venv_bin" ]; then
        has_venv=1
    elif [ "$rec_method" = venv ]; then
        has_venv=1
        rec_venv_bin=$(state_value bin)
        [ -n "$rec_venv_bin" ] || rec_venv_bin=$bin_dir
    fi
}

# Write the state file from method, command_dir and rec_* (to a new file, then moved).
write_state() {
    mkdir -p "$home_dir" || return 1
    {
        say "method=$method"
        say "bin=$command_dir"
        if [ "$has_uv" = 1 ]; then
            say "uv=$rec_uv"
            say "tool_dir=$rec_tool_dir"
            say "tool_bin=$rec_tool_bin"
        fi
        if [ "$has_venv" = 1 ]; then
            say "venv_bin=$rec_venv_bin"
        fi
    } >"$state.new" || return 1
    mv -f "$state.new" "$state"
}

# Remove the virtual environment of this script and the links to it.
remove_venv_install() {
    remove_links "${rec_venv_bin:-$bin_dir}" "$venv/bin/" || return 1
    if [ -d "$venv" ]; then
        run rm -rf "$venv" || return 1
    fi
    return 0
}

by_hand() {
    warn "To remove it by hand: delete the folder $rec_tool_dir/$PACKAGE and the links to it in"
    warn "$rec_tool_bin, then run this script with --uninstall again. Or install uv ($UV_MANUAL)"
    warn "and run this script with --uninstall again."
}

# Remove the uv tool that the state file records: the one in the recorded tool directory,
# with its commands in the recorded folder, whatever UV_TOOL_DIR and UV_TOOL_BIN_DIR are
# now. Fails, having changed nothing, when that cannot be done.
remove_uv_install() {
    case $rec_tool_dir:$rec_tool_bin in
        /*:/*) ;;
        *)
            warn "install.sh: $state does not say which tool directory of uv holds $PACKAGE (it was written by an"
            warn "earlier version of this script, and ${rec_tool_bin:-the command folder}/$PACKAGE does not lead to one), so nothing of uv's was removed."
            warn "Remove the tool with the uv that installed it (uv tool uninstall $PACKAGE), delete"
            warn "$state, then run this script with --uninstall again."
            return 1 ;;
    esac
    if [ ! -e "$rec_tool_dir/$PACKAGE" ] && [ ! -L "$rec_tool_dir/$PACKAGE" ]; then
        # Not there (an installation that never got that far, or removed with uv by hand):
        # only links that lead to where it was are left to remove.
        remove_links "$rec_tool_bin" "$rec_tool_dir/$PACKAGE/"
        return
    fi
    old_uv=""
    path_uv=$(program uv) || path_uv=""
    for candidate in "$rec_uv" "$path_uv" "$own_uv_dir/uv"; do
        case $candidate in
            /*) ;;
            *) continue ;;
        esac
        if [ -f "$candidate" ] && [ -x "$candidate" ] && uv_new_enough "$candidate"; then
            old_uv=$candidate
            break
        fi
    done
    env=$(program env) || env=""
    if [ -z "$old_uv" ] || [ -z "$env" ]; then
        warn "install.sh: $PACKAGE is installed as a uv tool in $rec_tool_dir/$PACKAGE, and the uv that installed it"
        warn "(${rec_uv:-not recorded}) was not found, nor another uv $UV_MINIMUM or later: the tool was left in place."
        by_hand
        return 1
    fi
    if ! run "$env" UV_TOOL_DIR="$rec_tool_dir" UV_TOOL_BIN_DIR="$rec_tool_bin" "$old_uv" --no-config tool uninstall "$PACKAGE"; then
        if [ -f "$rec_tool_dir/$PACKAGE/uv-receipt.toml" ]; then
            warn "install.sh: uv did not uninstall $PACKAGE from $rec_tool_dir (its message is above): the tool was left in place."
            by_hand
            return 1
        fi
        # No receipt: an environment that a run of this script did not finish, which uv
        # does not count as a tool.
        if ! run rm -rf "${rec_tool_dir:?}/$PACKAGE"; then
            warn "install.sh: $rec_tool_dir/$PACKAGE could not be removed."
            by_hand
            return 1
        fi
    fi
    if [ -e "$rec_tool_dir/$PACKAGE" ] || [ -L "$rec_tool_dir/$PACKAGE" ]; then
        if [ -f "$rec_tool_dir/$PACKAGE/uv-receipt.toml" ]; then
            warn "install.sh: uv reported success, and $rec_tool_dir/$PACKAGE is still there."
            by_hand
            return 1
        fi
        if ! run rm -rf "${rec_tool_dir:?}/$PACKAGE"; then
            warn "install.sh: $rec_tool_dir/$PACKAGE could not be removed."
            by_hand
            return 1
        fi
    fi
    remove_links "$rec_tool_bin" "$rec_tool_dir/$PACKAGE/"
}

uninstall() {
    read_state
    removed=0
    # uv's tool first: when it cannot be removed, nothing else is, and the record stays.
    if [ "$has_uv" = 1 ]; then
        if ! remove_uv_install; then
            warn "install.sh: nothing else was removed, and the record $state is kept."
            exit 1
        fi
        removed=1
    fi
    if [ "$has_venv" = 1 ]; then
        remove_venv_install || die "the virtual environment $venv could not be removed; the record $state is kept."
        removed=1
    fi
    if [ -d "$dist_dir" ]; then
        run rm -rf "$dist_dir" || die "$dist_dir could not be removed; the record $state is kept."
        removed=1
    fi
    if [ -d "$own_uv_dir" ]; then
        run rm -rf "$own_uv_dir" || die "$own_uv_dir could not be removed; the record $state is kept."
        removed=1
        say "The uv that this script downloaded is removed. Pythons and cached files that uv"
        say "downloaded stay in uv's own folders (${XDG_DATA_HOME:-$HOME/.local/share}/uv and ${XDG_CACHE_HOME:-$HOME/.cache}/uv)."
    fi
    rm -f "$state" "$state.new" || die "$state could not be removed."
    rmdir "$home_dir" 2>/dev/null || true
    if [ "$removed" = 1 ]; then
        say "Removed $PACKAGE."
    else
        say "Nothing to remove: this script has no installation of $PACKAGE here."
    fi
}

# The SHA-256 of the file $1 as 64 hexadecimal digits, with the program found by
# install_uv; nothing when it could not be computed.
sha256_of() {
    case $digest_with in
        sha256sum) "$digest_tool" "$1" ;;
        shasum) "$digest_tool" -a 256 "$1" ;;
        openssl) "$digest_tool" dgst -sha256 -r "$1" ;;
    esac 2>/dev/null | sed -n '1s/^\([0-9a-f]\{64\}\)[ *].*$/\1/p'
}

install_uv() {
    curl=$(program curl) || curl=""
    wget=$(program wget) || wget=""
    shell=$(program sh) || die "sh was not found on PATH."
    env=$(program env) || die "env was not found on PATH."
    if [ -z "$curl$wget" ]; then
        warn "install.sh: uv has to be downloaded, and neither curl nor wget is installed."
        warn "Nothing was installed. Install curl or wget, or uv itself"
        warn "($UV_MANUAL), then run this script again."
        exit 1
    fi
    if [ -z "$curl" ] && ! "$wget" --help 2>&1 | grep -q -e '--https-only'; then
        die "this wget cannot be limited to https. Install curl, then run this script again."
    fi
    digest_tool=""
    for digest_with in sha256sum shasum openssl; do
        if digest_tool=$(program "$digest_with"); then
            break
        fi
        digest_tool=""
    done
    if [ -z "$digest_tool" ]; then
        warn "install.sh: uv has to be downloaded, and what is downloaded cannot be checked: none of"
        warn "sha256sum, shasum and openssl is installed. Nothing was installed. Install one of"
        warn "them, or uv itself ($UV_MANUAL), then run this script again."
        exit 1
    fi
    case $tmp in
        *:*) die "the temporary folder $tmp has a colon in its name, so it cannot be put on PATH for uv's installer. Set TMPDIR to another folder. Nothing was installed." ;;
    esac
    say "$1: downloading uv $UV_VERSION with its installer ($UV_INSTALLER, saved to a temporary file, checked against the SHA-256 in this script and run with sh) into $own_uv_dir; no shell profile is changed."
    confirm "Download and run the uv installer?"
    case $UV_INSTALLER in
        /*) run cp -- "$UV_INSTALLER" "$tmp/uv-install.sh" || die "$UV_INSTALLER could not be read. Nothing was installed." ;;
        *) download "$UV_INSTALLER" "$tmp/uv-install.sh" || die "the installer of uv could not be downloaded from $UV_INSTALLER. Nothing was installed. Try again later, or install uv by hand ($UV_MANUAL)." ;;
    esac
    if [ "$dry" != 1 ]; then
        # Nothing of the file is run, and no line of it is acted on, before this comparison.
        found=$(sha256_of "$tmp/uv-install.sh") || found=""
        if [ "$found" != "$UV_INSTALLER_SHA256" ]; then
            warn "install.sh: the file from $UV_INSTALLER is not the installer of uv $UV_VERSION that this script"
            warn "was written for: its SHA-256 is ${found:-unknown}"
            warn "and $UV_INSTALLER_SHA256 is expected."
            warn "It was not run. Nothing was installed. Install uv by hand ($UV_MANUAL),"
            warn "then run this script again; or run it with --no-uv, which uses a Python 3.11 to 3.13 on PATH."
            exit 1
        fi
        if ! installer_new_enough "$tmp/uv-install.sh"; then
            die "the file from $UV_INSTALLER is not the installer of uv $UV_MINIMUM or later (older installers change shell profiles): it was not run. Nothing was installed."
        fi
        # The installer compares the archive of uv with the SHA-256 it carries, and skips
        # that when no command named sha256sum is found. It gets one, first on its PATH.
        mkdir "$tmp/checked" || die "$tmp/checked could not be made. Nothing was installed."
        {
            say '#!/bin/sh'
            case $digest_with in
                sha256sum) say "exec $(quoted "$digest_tool") \"\$@\"" ;;
                shasum) say "exec $(quoted "$digest_tool") -a 256 \"\$@\"" ;;
                openssl) say 'for last in "$@"; do :; done'
                         say "exec $(quoted "$digest_tool") dgst -sha256 -r \"\$last\"" ;;
            esac
        } >"$tmp/checked/sha256sum" || die "$tmp/checked/sha256sum could not be written. Nothing was installed."
        chmod 700 "$tmp/checked/sha256sum" || die "$tmp/checked/sha256sum could not be made executable. Nothing was installed."
        say "The installer checks the archive of uv against the SHA-256 it carries (computed with $digest_tool)."
    fi
    # UV_UNMANAGED_INSTALL: uv goes into that folder and nowhere else, no shell profile and
    # no environment setting is changed, and no update record is written. UV_NO_MODIFY_PATH
    # says the same about profiles once more. Variables that would send uv elsewhere are
    # not passed on.
    unset UV_INSTALL_DIR CARGO_DIST_FORCE_INSTALL_DIR
    script_path=$PATH
    if [ "$dry" != 1 ]; then
        PATH=$tmp/checked:$PATH
    fi
    if ! run "$env" UV_UNMANAGED_INSTALL="$own_uv_dir" UV_NO_MODIFY_PATH=1 INSTALLER_NO_MODIFY_PATH=1 "$shell" "$tmp/uv-install.sh"; then
        PATH=$script_path
        die "the installer of uv failed (its message is above). Nothing was installed. Try again later, or install uv by hand ($UV_MANUAL)."
    fi
    PATH=$script_path
    uv=$own_uv_dir/uv
    if [ "$dry" != 1 ]; then
        case $("$uv" --version 2>/dev/null) in
            "uv $UV_VERSION"|"uv $UV_VERSION "*) ;;
            *) die "the uv installer did not leave a working uv $UV_VERSION in $own_uv_dir." ;;
        esac
    fi
}

# `uv tool install` of the package, run in the folder $1 with the requirement $2.
# --force replaces commands that are already there (an earlier or interrupted run);
# --reinstall-package installs cdlbib again from the source, so a changed checkout or
# branch is picked up, while the other packages are only brought up to date.
# pip goes into the environment so that cdlbib can install an optional extra later,
# also when uv is not on PATH. --no-config: no uv.toml or pyproject.toml of any folder
# (or of the user) changes what is installed or from where; uv's environment variables
# still apply.
tool_install() {
    (cd "$1" && "$uv" --no-config tool install --python "$PYTHON_REQUEST" --with pip --force \
        --reinstall-package "$PACKAGE" -- "$2")
}

# The same installation made beside the one that is there: into a tool directory in the
# temporary folder, where its command is then run. Nothing of the installed one is touched.
# What uv prints is shown only when this fails.
staged_install() {
    stage=$tmp/stage
    say "The installed $PACKAGE runs: it is kept until the new version has been installed beside it and has run."
    say "+ cd $(quoted "$1") && $(quoted "$env" UV_TOOL_DIR="$stage/tools" UV_TOOL_BIN_DIR="$stage/bin" "$uv" --no-config tool install --python "$PYTHON_REQUEST" --with pip --force -- "$2")"
    rm -rf "$stage" || return 1
    mkdir "$stage" || return 1
    if ! (cd "$1" && "$env" UV_TOOL_DIR="$stage/tools" UV_TOOL_BIN_DIR="$stage/bin" "$uv" --no-config tool install \
            --python "$PYTHON_REQUEST" --with pip --force -- "$2") >"$stage/log" 2>&1; then
        cat "$stage/log" >&2
        return 1
    fi
    say "+ $(quoted "$stage/bin/$PACKAGE" --version)"
    if ! "$stage/bin/$PACKAGE" --version >"$stage/log" 2>&1; then
        cat "$stage/log" >&2
        return 1
    fi
    rm -rf "$stage"
}

# Does the installed command run?
command_runs() {
    [ -n "$command_dir" ] && [ -x "$command_dir/$PACKAGE" ] && "$command_dir/$PACKAGE" --version >/dev/null 2>&1
}

# Stop after a step failed, saying what became of the installation that was there.
failed() {
    if [ "$working" = 1 ] && command_runs; then
        die "$1 The installation that was there is unchanged: $command_dir/$PACKAGE runs as before."
    fi
    die "$1 No working $PACKAGE was installed."
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

    # CDLBIB_UV_INSTALLER (for the tests of this script) names another place to read the
    # installer of uv from: an address on uv's own site, or a file. It changes where the
    # bytes come from and nothing else: the file is run only when its SHA-256 is
    # UV_INSTALLER_SHA256, like the one from the usual address. No setting of the
    # environment changes that digest or switches the comparison off.
    case ${CDLBIB_UV_INSTALLER:-} in
        '') ;;
        /*)
            [ -f "$CDLBIB_UV_INSTALLER" ] || die "CDLBIB_UV_INSTALLER names a file that does not exist."
            UV_INSTALLER=$CDLBIB_UV_INSTALLER ;;
        *..*|*[!A-Za-z0-9./:-]*) die "CDLBIB_UV_INSTALLER takes an address of the form https://astral.sh/uv/VERSION/install.sh, or the full path of a file." ;;
        https://astral.sh/uv/[0-9]*/install.sh) UV_INSTALLER=$CDLBIB_UV_INSTALLER ;;
        *) die "CDLBIB_UV_INSTALLER takes an address of the form https://astral.sh/uv/VERSION/install.sh, or the full path of a file." ;;
    esac

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
            warn "or with Python 3.11, 3.12 or 3.13:"
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
    dist_dir=$home_dir/dist
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
                warn "no Python 3.11, 3.12 or 3.13 was found on PATH."
            fi
            warn "Nothing was installed. Install one of these, then run this script again:"
            warn "  uv $UV_MINIMUM or later (https://docs.astral.sh/uv/getting-started/installation/;"
            warn "    an installed uv is updated with: uv self update)"
            warn "  Python 3.11, 3.12 or 3.13 with its venv module (macOS: https://www.python.org/downloads/"
            warn "    or brew install python; Debian/Ubuntu: apt-get install python3 python3-venv)"
            warn "or run the script without --no-uv, which downloads uv."
            exit 1
        fi
    fi

    need_git
    if [ "$method" = uv ] && [ "$source" = local ]; then
        # uv cannot install a file whose path has one of these characters, however the
        # path is written; refused here, before anything is downloaded.
        odd=$(printf '%s|' "$dist_dir" | LC_ALL=C tr -d 'A-Za-z0-9._~/ \200-\377-')
        if [ "$odd" != '|' ]; then
            die "uv cannot install from $dist_dir (the path has a character other than letters, digits, spaces and . _ ~ / -). Set XDG_DATA_HOME to a folder without such characters, or use --no-uv. Nothing was installed."
        fi
    fi
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

    # What is there now. A command that runs is kept until the new version is known to
    # work; only a command that does not run counts as a broken installation.
    read_state
    tools=""
    command_dir=""
    working=0
    wheel=""
    old_venv_bin=""
    if [ "$dry" != 1 ]; then
        if [ "$method" = uv ]; then
            env=$(program env) || die "env was not found on PATH."
            tools=$("$uv" --no-config tool dir) || die "uv did not name its tool directory. Nothing was installed."
            command_dir=$("$uv" --no-config tool dir --bin) || die "uv did not name the folder of its commands. Nothing was installed."
            case $tools:$command_dir in
                /*:/*) ;;
                *) die "uv named a tool directory or a command folder that is not a full path ($tools, $command_dir). Nothing was installed." ;;
            esac
            # One installation per record: an installation recorded elsewhere is not
            # left behind without a record.
            if [ "$has_uv" = 1 ] && [ -n "$rec_tool_dir" ] && [ -e "$rec_tool_dir/$PACKAGE" ]; then
                if [ "$rec_tool_dir" != "$tools" ] || [ "$rec_tool_bin" != "$command_dir" ]; then
                    warn "install.sh: this script installed $PACKAGE into uv's tool directory $rec_tool_dir (commands in"
                    warn "$rec_tool_bin); uv's tool directory is now $tools (commands in $command_dir)."
                    warn "Nothing was changed. Either run this script with UV_TOOL_DIR=$rec_tool_dir and"
                    warn "UV_TOOL_BIN_DIR=$rec_tool_bin, or remove that installation first with --uninstall."
                    exit 1
                fi
            fi
        else
            command_dir=$bin_dir
        fi
        if command_runs; then
            working=1
        fi
        # Recorded before the work starts, so that --uninstall also removes an unfinished
        # installation. An installation by the other route stays recorded until it is removed.
        if [ "$method" = uv ]; then
            has_uv=1
            rec_uv=$uv
            rec_tool_dir=$tools
            rec_tool_bin=$command_dir
        else
            old_venv_bin=$rec_venv_bin
            has_venv=1
            rec_venv_bin=$bin_dir
        fi
        write_state || die "$state could not be written. Nothing was installed."
    fi

    case $method in
        uv)
            if [ "$dry" != 1 ] && ! "$uv" --no-config python find "$PYTHON_REQUEST" >/dev/null 2>&1; then
                say "No Python 3.11, 3.12 or 3.13 was found: uv downloads one into its own folder ($("$uv" --no-config python dir)); the default python is not changed."
            fi
            # An installation whose command does not run (an interrupted run, deleted files)
            # is removed first, so that the result is the same as a first installation.
            if [ "$dry" != 1 ] && [ "$working" != 1 ]; then
                if [ -e "$tools/$PACKAGE" ] || [ -L "$tools/$PACKAGE" ]; then
                    say "The $PACKAGE tool in $tools does not run: it is removed and installed again."
                    "$uv" --no-config tool uninstall "$PACKAGE" >/dev/null 2>&1 || true
                    rm -rf "${tools:?}/$PACKAGE" || die "$tools/$PACKAGE could not be removed."
                fi
            fi
            if [ "$source" = local ]; then
                # A checkout is never named to `uv tool install`: uv records where a tool came
                # from and `uv tool upgrade` installs from there again. A wheel is built from
                # the checkout in the temporary folder and put into a folder of the user's own,
                # and that file is what uv installs and records. uv runs inside that folder and
                # is given the file's name only, so no path is part of the requirement. The new
                # wheel lies in dist/.new until the new version has run; the wheel of the
                # installed version is not touched before that.
                run "$uv" --no-config build --wheel --python "$PYTHON_REQUEST" --out-dir "$tmp/dist" -- "$checkout" \
                    || failed "uv could not build a wheel from $checkout (its message is above)."
                if [ "$dry" = 1 ]; then
                    say "+ cp $(quoted "$tmp/dist/$PACKAGE-VERSION-py3-none-any.whl") $(quoted "$dist_dir/")"
                    say "+ cd $(quoted "$dist_dir") && $(quoted "$uv" --no-config tool install --python "$PYTHON_REQUEST" --with pip --force --reinstall-package "$PACKAGE" -- "./$PACKAGE-VERSION-py3-none-any.whl$bracket")"
                else
                    set -- "$tmp/dist/$PACKAGE"-*.whl
                    if [ $# -ne 1 ] || [ ! -f "$1" ]; then
                        failed "uv built no wheel of $PACKAGE in $tmp/dist."
                    fi
                    wheel=${1##*/}
                    case $wheel in
                        *[!A-Za-z0-9._-]*) failed "the wheel that was built has an unexpected name: $wheel." ;;
                    esac
                    mkdir -p "$dist_dir" || failed "$dist_dir could not be made."
                    chmod 700 "$dist_dir" || failed "$dist_dir could not be made private."
                    rm -rf "$dist_dir/.new" || failed "$dist_dir/.new could not be removed."
                    mkdir "$dist_dir/.new" || failed "$dist_dir/.new could not be made."
                    cp "$1" "$dist_dir/.new/$wheel" || failed "the wheel could not be copied into $dist_dir."
                    rm -rf "$tmp/dist" || failed "$tmp/dist could not be removed."
                    if [ "$working" = 1 ]; then
                        if ! staged_install "$dist_dir/.new" "./$wheel$bracket"; then
                            rm -rf "$dist_dir/.new"
                            failed "The new version could not be installed (uv's message is above)."
                        fi
                    fi
                    mv -f "$dist_dir/.new/$wheel" "$dist_dir/$wheel" || failed "the wheel could not be moved into $dist_dir."
                    rmdir "$dist_dir/.new" || failed "$dist_dir/.new could not be removed."
                    install_in=$dist_dir
                    requirement=./$wheel$bracket
                    say "+ cd $(quoted "$dist_dir") && $(quoted "$uv" --no-config tool install --python "$PYTHON_REQUEST" --with pip --force --reinstall-package "$PACKAGE" -- "$requirement")"
                fi
            else
                if [ "$working" = 1 ]; then
                    staged_install "$tmp" "$spec" || failed "The new version could not be installed (uv's message is above)."
                fi
                install_in=$tmp
                requirement=$spec
                say "+ $(quoted "$uv" --no-config tool install --python "$PYTHON_REQUEST" --with pip --force --reinstall-package "$PACKAGE" -- "$spec")"
            fi
            if [ "$dry" != 1 ] && ! tool_install "$install_in" "$requirement"; then
                if command_runs; then
                    die "uv could not install $PACKAGE (its message is above). The installation that was there still runs: $command_dir/$PACKAGE."
                fi
                # No command that runs: what an interrupted run left behind can stop uv, so
                # the tool is removed and installed from nothing, once.
                say "Trying again after removing the unfinished $PACKAGE tool."
                "$uv" --no-config tool uninstall "$PACKAGE" >/dev/null 2>&1 || true
                rm -rf "${tools:?}/$PACKAGE" || die "$tools/$PACKAGE could not be removed."
                tool_install "$install_in" "$requirement" \
                    || die "uv could not install $PACKAGE (its message is above). No working $PACKAGE was installed; run this script again when the cause is gone."
            fi ;;
        venv)
            if [ "$dry" != 1 ] && [ -d "$venv" ] && ! "$venv/bin/python" -I -c 'import sys, pip
raise SystemExit(0 if (3, 11) <= sys.version_info[:2] <= (3, 13) else 1)' 2>/dev/null; then
                # Not a working environment (an interrupted run, or its Python is gone).
                run rm -rf "$venv" || die "$venv could not be removed."
            fi
            if [ ! -x "$venv/bin/python" ]; then
                run mkdir -p "$home_dir" || failed "$home_dir could not be made."
                if ! run "$python" -I -m venv "$venv"; then
                    # A Python that is reached through a link in another folder can fail
                    # here; the program the link leads to is tried once.
                    rm -rf "$venv" || failed "$venv could not be removed."
                    real=$("$python" -I -B -c 'import os, sys
print(os.path.realpath(sys.executable))') || failed "$python could not make a virtual environment."
                    run "$real" -I -m venv "$venv" || failed "$real could not make a virtual environment in $venv."
                fi
            fi
            # pip downloads and builds everything before it takes the installed version out
            # of the environment, so a source that cannot be installed leaves it as it was.
            run "$venv/bin/python" -I -m pip install --disable-pip-version-check --upgrade -- "$spec" \
                || failed "pip could not install $PACKAGE (its message is above)."
            run mkdir -p "$bin_dir" || failed "$bin_dir could not be made."
            if [ "$dry" = 1 ]; then
                say "+ ln -sf $(quoted "$venv/bin/$PACKAGE") $(quoted "$bin_dir/$PACKAGE")   (and each other command of the package)"
            else
                "$venv/bin/$PACKAGE" --version >/dev/null || failed "$venv/bin/$PACKAGE was installed but '$PACKAGE --version' failed."
                names=$(console_scripts "$venv/bin/python") || failed "the commands of $PACKAGE could not be listed."
                # The new environment runs: an earlier installation made with uv goes now.
                if [ "$has_uv" = 1 ]; then
                    say "Replacing the earlier installation (made with uv)."
                    if remove_uv_install; then
                        has_uv=0
                        rm -rf "$dist_dir" || die "$dist_dir could not be removed."
                    else
                        warn "install.sh: the earlier installation stays recorded in $state; --uninstall will try again."
                    fi
                fi
                for name in $names; do
                    if [ -e "$bin_dir/$name" ] && [ ! -L "$bin_dir/$name" ]; then
                        die "$bin_dir/$name exists and is not a link; it was left alone. Move it away, then run this script again."
                    fi
                    run ln -sf "$venv/bin/$name" "$bin_dir/$name" || die "the link $bin_dir/$name could not be made."
                done
                if [ -n "$old_venv_bin" ] && [ "$old_venv_bin" != "$bin_dir" ]; then
                    remove_links "$old_venv_bin" "$venv/bin/" || die "the links in $old_venv_bin could not be removed."
                fi
            fi ;;
    esac

    if [ "$dry" = 1 ]; then
        say "Nothing was installed. Run the script without --ask, or in a terminal, to install."
        exit 1
    fi

    version=$("$command_dir/$PACKAGE" --version) || die "$command_dir/$PACKAGE was installed but '$PACKAGE --version' failed."
    # The new version runs. What it replaced goes now: older wheels, and an installation
    # made by the other route.
    if [ "$method" = uv ]; then
        if [ -n "$wheel" ]; then
            for old in "$dist_dir"/*.whl; do
                if [ "$old" != "$dist_dir/$wheel" ] && [ -f "$old" ]; then
                    rm -f "$old" || die "$old could not be removed."
                fi
            done
        fi
        if [ "$has_venv" = 1 ]; then
            say "Replacing the earlier installation (made with venv)."
            remove_venv_install || die "the earlier virtual environment $venv could not be removed; it stays recorded in $state."
            has_venv=0
        fi
    fi
    write_state || die "$state could not be written."
    say ""
    say "Installed: $version"
    say "Command:   $command_dir/$PACKAGE (installed with $method)"
    path_line "$command_dir"
}

main "$@"
