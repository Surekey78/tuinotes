"""Modal dialogs: confirm, prompt and the keybinding/help reference."""

from __future__ import annotations

from typing import List, Optional

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Input, Static

from tuinotes import __version__
from tuinotes.commands import help_lines


class ConfirmScreen(ModalScreen[bool]):
    """A small yes/no dialog (used before deleting a note)."""

    DEFAULT_CSS = """
    ConfirmScreen { align: center middle; }
    ConfirmScreen > Vertical {
        width: auto; max-width: 90%; height: auto; max-height: 80%;
        border: thick $primary; background: $surface; padding: 1 2;
    }
    ConfirmScreen .question { margin-bottom: 1; }
    ConfirmScreen Horizontal { height: auto; align: center middle; }
    ConfirmScreen Button { margin: 0 1; min-width: 12; }
    """

    def __init__(self, question: str, *, confirm_label: str = "Yes", cancel_label: str = "No") -> None:
        super().__init__()
        self.question = question
        self.confirm_label = confirm_label
        self.cancel_label = cancel_label

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(self.question, classes="question")
            with Horizontal():
                yield Button(self.confirm_label, id="yes", variant="error")
                yield Button(self.cancel_label, id="no", variant="primary")

    def on_mount(self) -> None:
        self.query_one("#yes", Button).focus()

    @on(Button.Pressed)
    def _button(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "yes")

    def key_escape(self) -> None:
        self.dismiss(False)

    def key_y(self) -> None:
        self.dismiss(True)

    def key_n(self) -> None:
        self.dismiss(False)


class PromptScreen(ModalScreen[Optional[str]]):
    """A one-line text prompt (new note title, rename, search pattern)."""

    DEFAULT_CSS = """
    PromptScreen { align: center middle; }
    PromptScreen > Vertical {
        width: auto; min-width: 50; max-width: 90%; height: auto;
        border: thick $primary; background: $surface; padding: 1 2;
    }
    PromptScreen .question { margin-bottom: 1; }
    PromptScreen Horizontal { height: auto; align: center middle; margin-top: 1; }
    PromptScreen Button { margin: 0 1; min-width: 10; }
    """

    def __init__(
        self,
        question: str,
        value: str = "",
        *,
        placeholder: str = "",
        ok_label: str = "OK",
    ) -> None:
        super().__init__()
        self.question = question
        self.value = value
        self.placeholder = placeholder
        self.ok_label = ok_label

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(self.question, classes="question")
            yield Input(self.value, placeholder=self.placeholder, id="answer")
            with Horizontal():
                yield Button(self.ok_label, id="ok", variant="success")
                yield Button("Cancel", id="cancel")

    def on_mount(self) -> None:
        answer = self.query_one("#answer", Input)
        answer.focus()
        answer.cursor_position = len(self.value)

    @on(Button.Pressed)
    def _button(self, event: Button.Pressed) -> None:
        if event.button.id == "ok":
            self.dismiss(self.query_one("#answer", Input).value)
        else:
            self.dismiss(None)

    @on(Input.Submitted)
    def _submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value)

    def key_escape(self) -> None:
        self.dismiss(None)


KEYBINDING_GROUPS: List[tuple] = [
    (
        "Everywhere",
        [
            ("ctrl+n", "New note"),
            ("ctrl+s", "Save"),
            ("ctrl+f", "Focus search"),
            ("ctrl+d", "Delete note"),
            ("ctrl+p", "Toggle preview"),
            ("ctrl+e", "Split view (edit + preview)"),
            ("ctrl+g", "Link graph"),
            ("ctrl+t", "Tag filter"),
            ("ctrl+r", "Reindex / refresh"),
            ("ctrl+q", "Quit"),
            ("f1 or ?", "This help"),
            ("ctrl+\\", "Command palette"),
            ("esc", "Back / cancel"),
        ],
    ),
    (
        "Note list",
        [
            ("enter", "Open the highlighted note"),
            ("/", "Search (title, #tags, body)"),
            ("n", "New note"),
            ("d", "Delete"),
            ("p", "Preview"),
            ("e", "Split view"),
            ("g", "Graph"),
            ("s", "Cycle sort order"),
            ("t", "Tag filter"),
            ("j / k or ↓ ↑", "Move"),
            ("tab", "Jump to the touch buttons"),
            (":", "Command mode"),
            ("q", "Quit"),
        ],
    ),
    (
        "Editor",
        [
            ("ctrl+s", "Save now"),
            ("ctrl+p", "Preview"),
            ("ctrl+e", "Split view"),
            ("ctrl+b", "Backlinks"),
            ("ctrl+l", "Toggle line numbers"),
            ("ctrl+w", "Toggle soft wrap"),
            ("ctrl+space", "Focus the command bar"),
            ("esc", "Back to the list (saves first)"),
        ],
    ),
    (
        "Search syntax",
        [
            ("#tag", "Only notes with this tag"),
            ("-#tag", "Exclude a tag"),
            ("in:folder", "Restrict to a folder"),
            ("title:word", "Search titles only"),
            ('"exact phrase"', "Phrase match"),
        ],
    ),
]


class HelpScreen(ModalScreen[None]):
    """Keybinding + command reference, grouped for quick scanning."""

    DEFAULT_CSS = """
    HelpScreen { align: center middle; }
    HelpScreen > Vertical {
        width: 92; max-width: 95%; height: 85%;
        border: thick $primary; background: $surface; padding: 0 1;
    }
    HelpScreen Static.title { text-style: bold; padding: 1 0 0 1; }
    HelpScreen DataTable { height: 1fr; }
    HelpScreen Horizontal { height: auto; align: center middle; padding: 1; }
    """

    BINDINGS = [("escape", "close", "Close"), ("q", "close", "Close")]

    def __init__(self, extra: Optional[List[tuple]] = None) -> None:
        super().__init__()
        self.extra = extra or []

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(f"tuinotes {__version__} — keys & commands", classes="title")
            yield DataTable(id="table", cursor_type="row")
            with Horizontal():
                yield Button("Close", id="close", variant="primary")

    def on_mount(self) -> None:
        table = self.query_one("#table", DataTable)
        table.add_columns("Key", "Action")
        for group, rows in KEYBINDING_GROUPS + self.extra:
            table.add_row(f"── {group} ──", "", key=group)
            for key, action in rows:
                table.add_row(key, action)
        table.add_row("── : commands ──", "", key="commands")
        for line in help_lines():
            name, _, description = line.partition(" — ")
            table.add_row(name, description)
        self.query_one("#close", Button).focus()

    @on(Button.Pressed)
    def _pressed(self, event: Button.Pressed) -> None:
        self.dismiss(None)

    def action_close(self) -> None:
        self.dismiss(None)

    def key_q(self) -> None:
        self.dismiss(None)


class MessageScreen(ModalScreen[None]):
    """Scrollable text (used for backlinks, trash, git status, ...)."""

    DEFAULT_CSS = """
    MessageScreen { align: center middle; }
    MessageScreen > Vertical {
        width: 92; max-width: 95%; height: 85%;
        border: thick $primary; background: $surface; padding: 0 1;
    }
    MessageScreen Static.title { text-style: bold; padding: 1 0 0 1; }
    MessageScreen Horizontal { height: auto; align: center middle; padding: 1; }
    """

    BINDINGS = [("escape", "close", "Close"), ("q", "close", "Close")]

    def __init__(self, title: str, body, *, rows: Optional[List[tuple]] = None) -> None:
        super().__init__()
        self.title_text = title
        self.body = body
        self.rows = rows or []

    def compose(self) -> ComposeResult:
        from textual.containers import VerticalScroll

        with Vertical():
            yield Static(self.title_text, classes="title")
            if self.rows:
                yield DataTable(id="table", cursor_type="row")
            else:
                with VerticalScroll():
                    yield Static(self.body, id="body", markup=False)
            with Horizontal():
                yield Button("Close", id="close", variant="primary")

    def on_mount(self) -> None:
        if self.rows:
            table = self.query_one("#table", DataTable)
            table.add_columns("Note", "Detail")
            for row in self.rows:
                table.add_row(*row)
        self.query_one("#close", Button).focus()

    @on(Button.Pressed)
    def _pressed(self, event: Button.Pressed) -> None:
        self.dismiss(None)

    def action_close(self) -> None:
        self.dismiss(None)

    def key_q(self) -> None:
        self.dismiss(None)
