"""Split view: editor on the left, live preview on the right.

On narrow terminals (a phone in portrait) the panes stack vertically instead, so
the split stays usable at 40 columns.
"""

from __future__ import annotations

import time

from rich.text import Text
from textual import events, on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Footer, Header, Input, Markdown, Static

from tuinotes import markdown_utils as md
from tuinotes.models import NoteRef
from tuinotes.storage import NoteStore
from tuinotes.tui.markdown_area import MarkdownArea


class SplitScreen(Screen):
    """Side-by-side editing and preview."""

    BINDINGS = [
        Binding("ctrl+s", "save_note", "Save"),
        Binding("ctrl+p", "focus_editor", "Editor"),
        Binding("ctrl+e", "go_back", "Editor only"),
        Binding("escape", "go_back", "Back"),
        Binding("ctrl+b", "show_backlinks", "Backlinks"),
        Binding("tab", "switch_pane", "Switch pane", show=False),
        Binding("question_mark", "show_help", "Help"),
    ]

    def __init__(self, store: NoteStore, ref: NoteRef) -> None:
        super().__init__()
        self.store = store
        self.ref = ref
        self.dirty = False
        self._saved_text = ""
        self._loading = True
        self._last_change = 0.0

    def compose(self) -> ComposeResult:
        config = self.app.config  # type: ignore[attr-defined]
        yield Header(show_clock=False)
        with Horizontal(id="panes"):
            yield MarkdownArea(
                id="editor",
                show_line_numbers=bool(config.editor.line_numbers),
                soft_wrap=True,
                tab_behavior="indent",
            )
            with Vertical(id="preview-pane"):
                yield Markdown("# loading…", id="preview")
        yield Static("", id="status")
        yield Input(placeholder=":w save · :q back · type to find", id="command")
        yield Footer()

    def on_mount(self) -> None:
        area = self.query_one("#editor", MarkdownArea)
        content = self.store.read_content(self.ref.path)
        self._loading = True
        area.text = content
        self._loading = False
        self._saved_text = area.text
        self.query_one("#preview", Markdown).update(content)
        self.sub_title = f"{self.ref.title} (split)"
        self._layout_panes()
        self.set_interval(0.35, self._sync_preview)
        area.focus()
        self.update_status()

    def _layout_panes(self) -> None:
        """Stack the panes vertically on narrow terminals (portrait phones)."""
        panes = self.query_one("#panes")
        narrow = (self.size.width or 80) < 78
        panes.set_class(narrow, "-stacked")

    def on_resize(self, event: events.Resize) -> None:
        self._layout_panes()
        self.update_status()

    @on(MarkdownArea.Changed)
    def _changed(self, event: MarkdownArea.Changed) -> None:
        if self._loading:
            return
        area = self.query_one("#editor", MarkdownArea)
        self.dirty = area.text != self._saved_text
        self._last_change = time.time()
        self.update_status()

    def _sync_preview(self) -> None:
        if not self.dirty or time.time() - self._last_change < 0.3:
            return
        area = self.query_one("#editor", MarkdownArea)
        self.query_one("#preview", Markdown).update(area.text)
        self.update_status()

    def update_status(self, message: str = "") -> None:
        area = self.query_one("#editor", MarkdownArea)
        text = area.text
        row, col = area.cursor_location
        parts = [
            (self.ref.title, "bold"),
            (f"  {row + 1}:{col + 1}", "dim"),
            (f"  {md.count_words(text)} words", ""),
            ("  split view", "dim cyan"),
        ]
        if message:
            parts.append((f"  {message}", "yellow"))
        elif self.dirty:
            parts.append(("  ● unsaved", "yellow"))
        self.query_one("#status", Static).update(Text.assemble(*parts))

    @on(Input.Submitted, "#command")
    def _command(self, event: Input.Submitted) -> None:
        value = event.value.strip()
        event.input.clear()
        if not value:
            return
        if value.startswith(":"):
            self.app.run_command(value[1:], context=self)  # type: ignore[attr-defined]
        else:
            area = self.query_one("#editor", MarkdownArea)
            offsets = md.find_occurrences(area.text, value)
            if offsets:
                area.move_cursor(md.location_of_offset(area.text, offsets[0]), center=True)
            else:
                self.notify(f'"{value}" not found')

    def save(self, silent: bool = True) -> bool:
        area = self.query_one("#editor", MarkdownArea)
        note = self.store.update(self.ref, area.text)
        self.ref = note.ref
        self._saved_text = area.text
        self.dirty = False
        self.update_status()
        if not silent:
            self.notify(f"saved {self.ref.title}")
        self.app.auto_commit(self.ref)  # type: ignore[attr-defined]
        return True

    def action_save_note(self) -> None:
        self.save(silent=False)

    def action_focus_editor(self) -> None:
        self.query_one("#editor", MarkdownArea).focus()

    def action_switch_pane(self) -> None:
        area = self.query_one("#editor", MarkdownArea)
        preview = self.query_one("#preview", Markdown)
        (preview if area.has_focus else area).focus()

    def action_show_backlinks(self) -> None:
        self.save()
        self.app.show_backlinks(self.ref)  # type: ignore[attr-defined]

    def action_go_back(self) -> None:
        self.save()
        self.app.back_to_list()  # type: ignore[attr-defined]

    def action_show_help(self) -> None:
        self.app.show_help()  # type: ignore[attr-defined]
