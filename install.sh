#!/bin/sh
# Installs clm-harness for the current user on macOS, Linux and WSL.
#
#   curl -LsSf https://raw.githubusercontent.com/himax12/clm-harness/main/install.sh | sh
#
# It installs uv if it is missing, then installs the harness as a uv tool in its own
# environment with its own Python. Nothing is installed system-wide and sudo is not used.
#
# CLM_HARNESS_SOURCE chooses what to install: a path, a git URL, or a PyPI name.
# Run from a checkout, it installs that checkout.
set -eu

REPO="git+https://github.com/himax12/clm-harness"

here=$(cd "$(dirname "$0")" 2>/dev/null && pwd || true)
if [ -n "${CLM_HARNESS_SOURCE:-}" ]; then
    source=$CLM_HARNESS_SOURCE
elif [ -n "$here" ] && grep -qs '^name = "clm-harness"' "$here/pyproject.toml"; then
    source=$here
else
    source=$REPO
fi

case $source in
git+*)
    command -v git >/dev/null 2>&1 || {
        echo "git is needed to install from $source. Install git and run this again." >&2
        exit 1
    }
    ;;
esac

if ! command -v uv >/dev/null 2>&1; then
    echo "Installing uv (https://docs.astral.sh/uv/) ..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    PATH="${XDG_BIN_HOME:-$HOME/.local/bin}:$HOME/.cargo/bin:$PATH"
    export PATH
fi

echo "Installing clm-harness from $source ..."
uv tool install --force --python 3.12 "$source"

bin=$(uv tool dir --bin)
case ":$PATH:" in
*":$bin:"*) ;;
*)
    echo
    echo "$bin is not on your PATH. Run 'uv tool update-shell' and open a new terminal,"
    echo "or use the full path below."
    ;;
esac

echo
"$bin/clm-harness" doctor --offline || true
echo
echo "Next:"
echo "  clm-harness setup     save your Anthropic API key"
echo "  clm-harness doctor    check everything, including the key"
echo "  clm-harness run \"your task\" --dir path/to/repo --sandbox docker"
