"""Rendered Markdown preview."""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import Screen
from textual.widgets import Footer, Header, Markdown, Static

from tuinotes.models import NoteRef
from tuinotes.storage import NoteStore


class PreviewScreen(Screen):
    """Read-only rendered view of a note."""

    BINDINGS = [
        Binding("e", "edit_note", "Edit"),
        Binding("ctrl+e", "split_note", "Split"),
        Binding("ctrl+b", "show_backlinks", "Backlinks"),
        Binding("ctrl+p", "go_back", "Back"),
        Binding("escape", "go_back", "Back"),
        Binding("question_mark", "show_help", "Help"),
    ]

    def __init__(self, store: NoteStore, ref: NoteRef) -> None:
        super().__init__()
        self.store = store
        self.ref = ref

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with VerticalScroll(id="preview-scroll"):
            yield Markdown("# loading…", id="preview")
        yield Static("", id="status")
        yield Footer()

    def on_mount(self) -> None:
        content = self.store.read_content(self.ref.path)
        self.query_one("#preview", Markdown).update(content)
        self.sub_title = self.ref.title
        self.query_one("#status", Static).update(
            Text.assemble(
                (self.ref.title, "bold"),
                (f"  {self.ref.word_count} words · {self.ref.char_count} chars", "dim"),
                ("  " + self.ref.tag_str if self.ref.tag_str else "", "cyan"),
                ("  e edit · ctrl+e split", "dim"),
            )
        )

    def action_edit_note(self) -> None:
        self.app.open_note(self.ref.path, mode="edit")  # type: ignore[attr-defined]

    def action_split_note(self) -> None:
        self.app.open_note(self.ref.path, mode="split")  # type: ignore[attr-defined]

    def action_show_backlinks(self) -> None:
        self.app.show_backlinks(self.ref)  # type: ignore[attr-defined]

    def action_go_back(self) -> None:
        self.app.back_to_list()  # type: ignore[attr-defined]

    def action_show_help(self) -> None:
        self.app.show_help()  # type: ignore[attr-defined]
