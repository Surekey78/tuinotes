"""tuinotes — fast Markdown notes for Termux and every other terminal.

The import surface of this package is deliberately tiny: the TUI (and therefore
Textual) is only imported when a command actually needs it, so `note "idea"`
starts in a few tens of milliseconds even on a phone.
"""

from __future__ import annotations

__version__ = "0.1.0"

__all__ = ["__version__"]
