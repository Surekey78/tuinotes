"""Colour themes.

Registered with :meth:`textual.app.App.register_theme` at start-up, so they show
up in the built-in theme picker (``ctrl+t`` / ``:theme nord``) alongside the
Textual built-ins.
"""

from __future__ import annotations

from typing import Dict, List

THEME_NAMES: List[str] = [
    "tuinotes-dark",
    "tuinotes-light",
    "gruvbox-dark",
    "gruvbox-light",
    "nord",
    "monokai-tuinotes",
    "solarized-dark",
    "tokyo-night",
]


def _themes():
    """Build the theme objects lazily so importing this module stays cheap."""
    from textual.theme import Theme

    return {
        "tuinotes-dark": Theme(
            name="tuinotes-dark",
            primary="#7aa2f7",
            secondary="#bb9af7",
            warning="#e0af68",
            error="#f7768e",
            success="#9ece6a",
            accent="#7dcfff",
            foreground="#c0caf5",
            background="#1a1b26",
            surface="#1f2335",
            panel="#24283b",
            dark=True,
        ),
        "tuinotes-light": Theme(
            name="tuinotes-light",
            primary="#1e66f5",
            secondary="#8839ef",
            warning="#df8e1d",
            error="#d20f39",
            success="#40a02b",
            accent="#04a5e5",
            foreground="#3c3836",
            background="#eff1f5",
            surface="#e6e9ef",
            panel="#dce0e8",
            dark=False,
        ),
        "gruvbox-dark": Theme(
            name="gruvbox-dark",
            primary="#fabd2f",
            secondary="#d3869b",
            warning="#fe8019",
            error="#fb4934",
            success="#b8bb26",
            accent="#83a598",
            foreground="#ebdbb2",
            background="#282828",
            surface="#32302f",
            panel="#3c3836",
            dark=True,
        ),
        "gruvbox-light": Theme(
            name="gruvbox-light",
            primary="#b57614",
            secondary="#8f3f71",
            warning="#af3a03",
            error="#9d0006",
            success="#79740e",
            accent="#076678",
            foreground="#3c3836",
            background="#fbf1c7",
            surface="#f2e5bc",
            panel="#ebdbb2",
            dark=False,
        ),
        "nord": Theme(
            name="nord",
            primary="#88c0d0",
            secondary="#b48ead",
            warning="#ebcb8b",
            error="#bf616a",
            success="#a3be8c",
            accent="#81a1c1",
            foreground="#eceff4",
            background="#2e3440",
            surface="#3b4252",
            panel="#434c5e",
            dark=True,
        ),
        "monokai-tuinotes": Theme(
            name="monokai-tuinotes",
            primary="#f92672",
            secondary="#ae81ff",
            warning="#e6db74",
            error="#f92672",
            success="#a6e22e",
            accent="#66d9ef",
            foreground="#f8f8f2",
            background="#272822",
            surface="#2e2f2a",
            panel="#3e3d32",
            dark=True,
        ),
        "solarized-dark": Theme(
            name="solarized-dark",
            primary="#268bd2",
            secondary="#6c71c4",
            warning="#b58900",
            error="#dc322f",
            success="#859900",
            accent="#2aa198",
            foreground="#93a1a1",
            background="#002b36",
            surface="#073642",
            panel="#0a4050",
            dark=True,
        ),
        "tokyo-night": Theme(
            name="tokyo-night",
            primary="#7aa2f7",
            secondary="#9d7cd8",
            warning="#ff9e64",
            error="#db4b4b",
            success="#73daca",
            accent="#bb9af7",
            foreground="#a9b1d6",
            background="#1a1b26",
            surface="#16161e",
            panel="#24283b",
            dark=True,
        ),
    }


def all_themes() -> Dict[str, object]:
    return _themes()


def register(app) -> None:
    """Register every tuinotes theme with a Textual app."""
    for theme in _themes().values():
        app.register_theme(theme)  # type: ignore[arg-type]


def is_dark(name: str) -> bool:
    theme = _themes().get(name)
    return bool(getattr(theme, "dark", True))
