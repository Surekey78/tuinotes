"""TUI layer for tuinotes (Textual).

Importing :mod:`tuinotes.tui` pulls in Textual, so the CLI only imports it when a
command really needs the interface.
"""

from __future__ import annotations

__all__ = ["run_app"]


def run_app(*args, **kwargs) -> int:  # pragma: no cover - thin wrapper
    """Import the app lazily and run it."""
    from tuinotes.tui.app import run_app as _run_app

    return _run_app(*args, **kwargs)
