"""Parsing for the vim-style ``:command`` mode (bonus challenge).

Parsing lives here (pure, unit-tested); execution lives in the app, which owns
the store, the config and the screen stack.
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

#: Commands understood by the TUI's ``:`` prompt (and by ``tuinotes cmd``).
COMMANDS: Dict[str, Dict[str, object]] = {
    "w": {"args": "", "help": "Save the current note", "scope": "editor"},
    "write": {"args": "", "help": "Save the current note", "scope": "editor"},
    "q": {"args": "", "help": "Go back / quit", "scope": "all"},
    "quit": {"args": "", "help": "Quit tuinotes", "scope": "all"},
    "wq": {"args": "", "help": "Save and go back", "scope": "editor"},
    "x": {"args": "", "help": "Save and go back", "scope": "editor"},
    "q!": {"args": "", "help": "Discard changes and go back", "scope": "editor"},
    "n": {"args": "[title]", "help": "New note", "scope": "all"},
    "new": {"args": "[title]", "help": "New note", "scope": "all"},
    "e": {"args": "<note>", "help": "Open a note", "scope": "all"},
    "edit": {"args": "<note>", "help": "Open a note", "scope": "all"},
    "o": {"args": "<note>", "help": "Open a note", "scope": "all"},
    "d": {"args": "[note]", "help": "Delete a note (to trash)", "scope": "all"},
    "delete": {"args": "[note]", "help": "Delete a note (to trash)", "scope": "all"},
    "restore": {"args": "<trashed>", "help": "Restore a trashed note", "scope": "all"},
    "s": {"args": "<query>", "help": "Search notes", "scope": "all"},
    "search": {"args": "<query>", "help": "Search notes", "scope": "all"},
    "g": {"args": "<query>", "help": "Search notes", "scope": "all"},
    "tag": {"args": "<tag> ...", "help": "Add tags to the current note", "scope": "editor"},
    "untag": {"args": "<tag> ...", "help": "Remove tags from the current note", "scope": "editor"},
    "tags": {"args": "", "help": "List tags with counts", "scope": "all"},
    "sort": {"args": "modified|newest|oldest|alphabetical|size", "help": "Sort the note list", "scope": "list"},
    "theme": {"args": "<name>", "help": "Switch theme", "scope": "all"},
    "daily": {"args": "", "help": "Open (or create) today's note", "scope": "all"},
    "template": {"args": "<name>", "help": "New note from a template", "scope": "all"},
    "templates": {"args": "", "help": "List templates", "scope": "all"},
    "preview": {"args": "", "help": "Toggle the rendered preview", "scope": "editor"},
    "split": {"args": "", "help": "Toggle edit + preview split view", "scope": "editor"},
    "backlinks": {"args": "[note]", "help": "Show notes linking here", "scope": "editor"},
    "graph": {"args": "[depth]", "help": "Show the link graph", "scope": "all"},
    "rename": {"args": "<new title>", "help": "Rename the current note", "scope": "editor"},
    "export": {"args": "html|md|txt|pdf [path]", "help": "Export the current note", "scope": "editor"},
    "git": {"args": "status|commit|push|pull|log|init", "help": "Git sync commands", "scope": "all"},
    "set": {"args": "<key> <value>", "help": "Change a setting (e.g. :set editor.line_numbers false)", "scope": "all"},
    "numbers": {"args": "", "help": "Toggle line numbers", "scope": "editor"},
    "vim": {"args": "", "help": "Toggle vim keymap", "scope": "editor"},
    "wrap": {"args": "", "help": "Toggle soft wrap", "scope": "editor"},
    "share": {"args": "", "help": "Share the note via the Android share sheet", "scope": "editor"},
    "voice": {"args": "[text]", "help": "Dictate a note (Termux:API)", "scope": "all"},
    "reindex": {"args": "", "help": "Rebuild the note index", "scope": "all"},
    "palette": {"args": "", "help": "Open the fuzzy command palette", "scope": "all"},
    "trash": {"args": "", "help": "Show the trash", "scope": "all"},
    "purge": {"args": "[days]", "help": "Empty expired trash", "scope": "all"},
    "reload": {"args": "", "help": "Reload the current note from disk", "scope": "editor"},
    "help": {"args": "[command]", "help": "Show keybindings / command help", "scope": "all"},
    "keys": {"args": "", "help": "Show the keybinding reference", "scope": "all"},
    "version": {"args": "", "help": "Show version information", "scope": "all"},
}

ALIASES: Dict[str, str] = {
    "write": "w",
    "quit": "q",
    "x": "wq",
    "new": "n",
    "edit": "e",
    "open": "e",
    "delete": "d",
    "rm": "d",
    "search": "s",
    "grep": "s",
    "num": "numbers",
    "set-option": "set",
    "ln": "numbers",
    "bl": "backlinks",
    "export-pdf": "export",
}

#: Commands that need a note open in the editor.
EDITOR_SCOPE = {
    name
    for name, spec in COMMANDS.items()
    if spec.get("scope") == "editor"
}


@dataclass(frozen=True)
class ParsedCommand:
    """A parsed ``:command`` line."""

    name: str
    args: Tuple[str, ...] = ()
    raw: str = ""
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error

    @property
    def arg_text(self) -> str:
        return " ".join(self.args)

    @property
    def first(self) -> str:
        return self.args[0] if self.args else ""


def parse_command(line: str) -> ParsedCommand:
    """Parse ``:wq``, ``tag programming rust``, ``export pdf out.pdf`` ..."""
    raw = (line or "").strip()
    if raw.startswith(":"):
        raw = raw[1:]
    if not raw:
        return ParsedCommand(name="", raw=line, error="empty command")
    try:
        tokens = shlex.split(raw, posix=True)
    except ValueError:
        tokens = raw.split()
    if not tokens:
        return ParsedCommand(name="", raw=line, error="empty command")
    name = tokens[0].lower()
    args = tuple(tokens[1:])
    canonical = ALIASES.get(name, name)
    if canonical not in COMMANDS:
        suggestions = ", ".join(suggest(name))
        return ParsedCommand(
            name=name, args=args, raw=line, error=f"unknown command :{name}"
            + (f" — did you mean {suggestions}?" if suggestions else " (:help)")
        )
    return ParsedCommand(name=canonical, args=args, raw=line)


def suggest(name: str, limit: int = 3) -> List[str]:
    """Prefix matches first, then simple substring matches."""
    names = sorted(set(COMMANDS) | set(ALIASES))
    prefix = [n for n in names if n.startswith(name)]
    substring = [n for n in names if name and name in n and n not in prefix]
    return (prefix + substring)[:limit]


def completions(prefix: str) -> List[Tuple[str, str]]:
    """``[(command, help)]`` for the ``:`` prompt's autocompletion."""
    prefix = prefix.lstrip(":").lower()
    out: List[Tuple[str, str]] = []
    for name in sorted(set(COMMANDS) | set(ALIASES)):
        if prefix and not name.startswith(prefix):
            continue
        spec = COMMANDS.get(name) or COMMANDS.get(ALIASES.get(name, ""), {})
        out.append((name, str(spec.get("help", ""))))
    return out


def help_lines(scope: Optional[str] = None) -> List[str]:
    """Human-readable command reference lines."""
    lines: List[str] = []
    for name, spec in COMMANDS.items():
        if name in ALIASES.values() and name not in COMMANDS:
            continue
        if scope and spec.get("scope") not in (scope, "all"):
            continue
        args = str(spec.get("args", ""))
        lines.append(f":{name} {args}".rstrip() + f" — {spec.get('help', '')}")
    return lines
