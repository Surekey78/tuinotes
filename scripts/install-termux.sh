#!/data/data/com.termux/files/usr/bin/bash
#
# tuinotes installer for Termux (Android).
#
#   bash <(curl -fsSL https://raw.githubusercontent.com/Surekey78/tuinotes/main/scripts/install-termux.sh)
#
# Idempotent: safe to re-run after updates. Works on Linux/macOS too (it just
# skips the Termux-only steps).
set -euo pipefail

BOLD=$'\033[1m'; DIM=$'\033[2m'; GREEN=$'\033[32m'; YELLOW=$'\033[33m'; RESET=$'\033[0m'
say()  { printf '%s\n' "${BOLD}==>${RESET} $*"; }
info() { printf '%s\n' "${DIM}    $*${RESET}"; }
warn() { printf '%s\n' "${YELLOW}  ! $*${RESET}"; }

is_termux() { [[ "${PREFIX:-}" == *com.termux* || -n "${TERMUX_VERSION:-}" ]]; }

say "tuinotes installer"

# ---------------------------------------------------------------- 1. packages
if is_termux; then
  say "Updating Termux packages"
  pkg update -y
  say "Installing python, git and termux-api"
  pkg install -y python git termux-api || pkg install -y python git
  if ! command -v termux-notification >/dev/null 2>&1; then
    warn "termux-api is missing — install the Termux:API app from F-Droid, then: pkg install termux-api"
  fi
else
  info "Not running inside Termux — skipping pkg install."
  for tool in python3 git; do
    command -v "$tool" >/dev/null 2>&1 || warn "$tool not found"
  done
fi

# ------------------------------------------------------------------ 2. python
say "Installing tuinotes"
PIP="pip"
command -v pip >/dev/null 2>&1 || PIP="python3 -m pip"
if command -v pipx >/dev/null 2>&1 && [[ "${TUINOTES_USE_PIPX:-0}" == "1" ]]; then
  pipx install termux-notes
else
  $PIP install --upgrade termux-notes
fi

# -------------------------------------------------------------- 3. the vault
NOTES_DIR="${TUINOTES_HOME:-$HOME/notes}"
say "Preparing the vault at $NOTES_DIR"
mkdir -p "$NOTES_DIR/.templates"

# ------------------------------------------------------- 4. Termux niceties
if is_termux; then
  if command -v tuinotes >/dev/null 2>&1; then
    say "Configuring Termux extra-keys (/, :, CTRL, arrows)"
    tuinotes setup termux || warn "could not write ~/.termux/termux.properties"
    say "Installing Termux:Widget shortcuts"
    tuinotes widget install || warn "could not install widgets"
  fi
else
  info "Skipping Termux extra-keys and widgets."
fi

# ------------------------------------------------------------------ 5. checks
say "Environment check"
if command -v tuinotes >/dev/null 2>&1; then
  tuinotes doctor || true
else
  warn "tuinotes is not on PATH — check your pip user bin directory"
fi

cat <<EOF

${GREEN}tuinotes is ready.${RESET}

  note "your first thought"     capture a note
  tuinotes daily --open         today's note
  tuinotes                      open the app
  tuinotes doctor               check the environment

Docs: https://github.com/Surekey78/tuinotes#readme
EOF
