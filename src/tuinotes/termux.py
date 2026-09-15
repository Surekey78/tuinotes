"""Termux integration: Termux:API wrappers, widgets and environment checks.

Every function degrades gracefully: when the ``termux-*`` binaries are missing
(a laptop, CI, ...) they either return ``None``/``False`` or raise
:class:`TermuxUnavailable`, so the rest of the app never branches on platform.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence

from tuinotes import __version__

TERMUX_PREFIX_MARKERS = ("com.termux", "/data/data/com.termux")
SHORTCUTS_DIR = Path.home() / ".shortcuts"
TERMUX_PROPERTIES = Path.home() / ".termux" / "termux.properties"

#: An extra-keys row tuned for note taking on a phone keyboard.
EXTRA_KEYS_ROW = (
    "extra-keys = [["
    "ESC,"
    "'/',"
    "':',"
    "CTRL,"
    "ALT,"
    "LEFT,"
    "DOWN,"
    "UP,"
    "RIGHT,"
    "TAB,"
    "'-'"
    "]]"
)


class TermuxUnavailable(RuntimeError):
    """Raised when a Termux:API feature is requested but not installed."""


@dataclass(frozen=True)
class TermuxInfo:
    """Environment facts used by ``tuinotes doctor``."""

    is_termux: bool
    api_available: bool
    missing: List[str]
    version: str = ""
    prefix: str = ""

    def describe(self) -> str:
        if not self.is_termux:
            return "not running inside Termux"
        status = "Termux:API ready" if self.api_available else "Termux:API missing"
        if self.missing:
            status += f" (missing: {', '.join(self.missing)})"
        return status


def is_termux() -> bool:
    """True when running inside Termux on Android."""
    prefix = os.environ.get("PREFIX", "")
    if any(marker in prefix for marker in TERMUX_PREFIX_MARKERS):
        return True
    if os.environ.get("TERMUX_VERSION"):
        return True
    return Path("/data/data/com.termux").is_dir()


def has_command(name: str) -> bool:
    return shutil.which(name) is not None


def detect(apis: Sequence[str] = ()) -> TermuxInfo:
    """Inspect the environment for Termux and the Termux:API helpers we use."""
    wanted = list(apis) or [
        "termux-notification",
        "termux-clipboard-set",
        "termux-clipboard-get",
        "termux-share",
        "termux-tts-speak",
        "termux-speech-to-text",
        "termux-vibrate",
        "termux-wake-lock",
        "termux-open-url",
    ]
    missing = [name for name in wanted if not has_command(name)]
    return TermuxInfo(
        is_termux=is_termux(),
        api_available=not missing,
        missing=missing,
        version=os.environ.get("TERMUX_VERSION", ""),
        prefix=os.environ.get("PREFIX", ""),
    )


def run_termux(
    command: str,
    *args: str,
    input_text: Optional[str] = None,
    timeout: float = 30.0,
    check: bool = True,
) -> Optional[subprocess.CompletedProcess]:
    """Run a ``termux-*`` helper. Returns ``None`` when it is not installed."""
    binary = shutil.which(command)
    if binary is None:
        if check:
            raise TermuxUnavailable(f"{command} not found — install with: pkg install termux-api")
        return None
    try:
        return subprocess.run(
            [binary, *args],
            input=input_text,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:  # pragma: no cover - device specific
        if check:
            raise TermuxUnavailable(f"{command} failed: {exc}") from exc
        return None


# --------------------------------------------------------------------- actions
def notify(title: str, content: str = "", *, id: str = "tuinotes", priority: str = "low") -> bool:
    """Post an Android notification (quick-capture reminder, save confirmation)."""
    result = run_termux(
        "termux-notification",
        "--title",
        title,
        "--content",
        content,
        "--id",
        id,
        "--priority",
        priority,
        check=False,
    )
    return bool(result and result.returncode == 0)


def cancel_notification(id: str = "tuinotes") -> bool:
    result = run_termux("termux-notification-remove", "--id", id, check=False)
    return bool(result and result.returncode == 0)


def clipboard_copy(text: str) -> bool:
    result = run_termux("termux-clipboard-set", input_text=text, check=False)
    return bool(result and result.returncode == 0)


def clipboard_paste() -> str:
    result = run_termux("termux-clipboard-get", check=False)
    return (result.stdout or "") if result else ""


def share_send(text: str, content_type: str = "text/plain") -> bool:
    """Send text to the Android share sheet."""
    result = run_termux(
        "termux-share", "-a", "send", "-c", content_type, input_text=text, check=False
    )
    return bool(result and result.returncode == 0)


def share_receive(content_type: str = "text/plain", timeout: float = 300.0) -> str:
    """Block until the user shares something into Termux, return the text."""
    result = run_termux(
        "termux-share",
        "-a",
        "send",
        "-c",
        content_type,
        "-r",
        timeout=timeout,
        check=False,
    )
    if result is None:
        raise TermuxUnavailable("termux-share not found — install with: pkg install termux-api")
    return (result.stdout or "").strip()


def speak(text: str) -> bool:
    result = run_termux("termux-tts-speak", input_text=text, check=False)
    return bool(result and result.returncode == 0)


def listen(timeout: float = 120.0) -> str:
    """Speech-to-text capture (bonus challenge: voice notes)."""
    result = run_termux("termux-speech-to-text", timeout=timeout, check=False)
    if result is None:
        raise TermuxUnavailable(
            "termux-speech-to-text not found — install with: pkg install termux-api"
        )
    return (result.stdout or "").strip()


def vibrate(milliseconds: int = 100) -> bool:
    result = run_termux("termux-vibrate", "-d", str(milliseconds), check=False)
    return bool(result and result.returncode == 0)


def wake_lock(acquire: bool = True) -> bool:
    command = "termux-wake-lock" if acquire else "termux-wake-unlock"
    result = run_termux(command, check=False)
    return bool(result and result.returncode == 0)


def open_url(url: str) -> bool:
    result = run_termux("termux-open-url", url, check=False)
    return bool(result and result.returncode == 0)


def battery() -> str:
    result = run_termux("termux-battery-status", check=False)
    return (result.stdout or "").strip() if result else ""


# --------------------------------------------------------------- Termux:Widget
QUICK_CAPTURE_SCRIPT = """#!/data/data/com.termux/files/usr/bin/bash
# tuinotes: capture a note from Termux:Widget
TEXT=$(termux-dialog text -t "Quick note" -i "What's on your mind?")
[ -z "$TEXT" ] && exit 0
note "$TEXT" && termux-toast "Note saved"
"""

DAILY_SCRIPT = """#!/data/data/com.termux/files/usr/bin/bash
# tuinotes: open (or create) today's note in the TUI
exec tuinotes daily --open
"""

VOICE_SCRIPT = """#!/data/data/com.termux/files/usr/bin/bash
# tuinotes: dictation → note
TEXT=$(termux-speech-to-text)
[ -z "$TEXT" ] && exit 0
note "$TEXT" && termux-toast "Voice note saved"
"""

SHARE_SCRIPT = """#!/data/data/com.termux/files/usr/bin/bash
# tuinotes: grab shared text and store it as a note
TEXT=$(termux-share -a send -c 'text/plain' -r)
[ -z "$TEXT" ] && exit 0
note "$TEXT" && termux-toast "Shared text saved"
"""

WIDGET_SCRIPTS = {
    "tuinotes-quick-note.sh": QUICK_CAPTURE_SCRIPT,
    "tuinotes-daily-note.sh": DAILY_SCRIPT,
    "tuinotes-voice-note.sh": VOICE_SCRIPT,
    "tuinotes-share-to-note.sh": SHARE_SCRIPT,
}


def widget_paths() -> List[Path]:
    return [SHORTCUTS_DIR / name for name in WIDGET_SCRIPTS]


def install_widgets() -> List[Path]:
    """Install Termux:Widget shortcuts into ``~/.shortcuts`` (bonus challenge)."""
    SHORTCUTS_DIR.mkdir(parents=True, exist_ok=True)
    created: List[Path] = []
    for name, body in WIDGET_SCRIPTS.items():
        target = SHORTCUTS_DIR / name
        target.write_text(body, encoding="utf-8")
        target.chmod(0o755)
        created.append(target)
    return created


def uninstall_widgets() -> List[Path]:
    removed: List[Path] = []
    for path in widget_paths():
        if path.is_file():
            path.unlink()
            removed.append(path)
    return removed


def list_widgets() -> List[Path]:
    return [path for path in widget_paths() if path.is_file()]


# ------------------------------------------------------------ termux.properties
def properties_needs_update() -> bool:
    """True when ``extra-keys`` is absent from the user's termux.properties."""
    if not TERMUX_PROPERTIES.is_file():
        return True
    return "extra-keys" not in TERMUX_PROPERTIES.read_text(encoding="utf-8", errors="replace")


def configure_properties(append: bool = True) -> Path:
    """Write a note-taking friendly ``extra-keys`` row.

    Termux has no API for the hardware volume keys, so the documented
    one-handed setup is a row of on-screen keys (``/``, ``:``, ``CTRL``, arrows)
    plus the in-app ``ctrl+up``/``ctrl+down`` bindings.
    """
    TERMUX_PROPERTIES.parent.mkdir(parents=True, exist_ok=True)
    existing = ""
    if TERMUX_PROPERTIES.is_file():
        existing = TERMUX_PROPERTIES.read_text(encoding="utf-8", errors="replace")
    if "extra-keys" in existing:
        lines = [
            EXTRA_KEYS_ROW if line.strip().startswith("extra-keys") else line
            for line in existing.splitlines()
        ]
        content = "\n".join(lines) + "\n"
    elif append and existing.strip():
        content = existing.rstrip() + "\n\n# tuinotes: note-taking keys\n" + EXTRA_KEYS_ROW + "\n"
    else:
        content = "# tuinotes: note-taking keys\n" + EXTRA_KEYS_ROW + "\n"
    TERMUX_PROPERTIES.write_text(content, encoding="utf-8")
    return TERMUX_PROPERTIES


def reload_settings() -> bool:
    result = run_termux("termux-reload-settings", check=False)
    return bool(result and result.returncode == 0)


def version_banner() -> str:
    return f"tuinotes {__version__} (termux={is_termux()})"
