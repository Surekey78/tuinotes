"""The editor screen: Markdown editing, autosave, vim keys and a command bar."""

from __future__ import annotations

import time
from typing import Optional

from rich.text import Text
from textual import events, on, work
from textual.actions import SkipAction
from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import Footer, Header, Input, Static

from tuinotes import markdown_utils as md
from tuinotes.models import NoteRef
from tuinotes.storage import NoteStore, StorageError
from tuinotes.tui.markdown_area import MarkdownArea
from tuinotes.tui.vim import INSERT, VimMode


class EditorScreen(Screen):
    """Full-screen Markdown editor with live statistics and autosave."""

    # priority=True so these win over TextArea's own editing bindings
    # (ctrl+w, ctrl+e, ctrl+d, ctrl+k, ctrl+u, ctrl+a are all taken there).
    BINDINGS = [
        Binding("ctrl+s", "save_note", "Save", priority=True),
        Binding("ctrl+p", "toggle_preview", "Preview", priority=True),
        Binding("ctrl+e", "toggle_split", "Split", priority=True),
        Binding("ctrl+b", "show_backlinks", "Backlinks", priority=True),
        Binding("ctrl+o", "go_back", "Back", priority=True),
        Binding("ctrl+l", "toggle_numbers", "Numbers", priority=True, show=False),
        Binding("ctrl+w", "toggle_wrap", "Wrap", priority=True, show=False),
        Binding("ctrl+g", "show_graph", "Graph", priority=True, show=False),
        Binding("ctrl+n", "new_note", "New", priority=True, show=False),
        Binding("ctrl+t", "add_tag", "Tag", priority=True, show=False),
        Binding("ctrl+space", "focus_command", "Command", priority=True, show=False),
        Binding("escape", "escape_key", "Back", priority=True),
        Binding("question_mark", "show_help", "Help", priority=True),
        Binding("ctrl+up", "page_up", "Page up", priority=True, show=False),
        Binding("ctrl+down", "page_down", "Page down", priority=True, show=False),
    ]

    def __init__(self, store: NoteStore, ref: NoteRef, *, new: bool = False) -> None:
        super().__init__()
        self.store = store
        self.ref = ref
        self.is_new = new
        self.dirty = False
        self._saved_text = ""
        self.last_saved = 0.0
        self._last_change = 0.0
        self._loading = True
        self.vim: Optional[VimMode] = None
        self.emacs = False

    # ------------------------------------------------------------------ layout
    def compose(self) -> ComposeResult:
        config = self.app.config  # type: ignore[attr-defined]
        yield Header(show_clock=False)
        area = MarkdownArea(
            id="editor",
            show_line_numbers=bool(config.editor.line_numbers),
            soft_wrap=bool(config.editor.soft_wrap),
            tab_behavior="indent",
        )
        area.indent_width = int(config.editor.tab_size or 4)
        yield area
        yield Static("", id="status")
        yield Input(
            placeholder=":w save · :q back · :tag idea · :export html — or type to find in note",
            id="command",
        )
        yield Footer()

    async def on_mount(self) -> None:
        config = self.app.config  # type: ignore[attr-defined]
        area = self.query_one("#editor", MarkdownArea)
        try:
            content = self.store.read_content(self.ref.path)
        except StorageError as error:
            content = ""
            self.notify(f"could not read note: {error}", severity="error")
        self._loading = True
        area.text = content
        self._loading = False
        self._saved_text = area.text
        area.move_cursor((0, 0))
        self.sub_title = self.ref.title
        self._setup_keymap(config.editor.keymap)
        self.update_status()
        if config.editor.autosave:
            self.set_interval(max(0.5, float(config.editor.autosave_interval)), self._autosave_tick)
        if not self.vim:
            area.focus()

    def _setup_keymap(self, keymap: str) -> None:
        """Apply a keymap.

        ``emacs`` hands ctrl+e / ctrl+w back to the widget (Emacs line-end and
        word-delete) by skipping our own actions for those keys.
        """
        area = self.query_one("#editor", MarkdownArea)
        self.emacs = keymap == "emacs"
        if keymap == "vim":
            self.vim = VimMode(
                area,
                on_search=self._on_vim_search,
                on_command=lambda prefix: self.action_focus_command(prefix),
                on_status=self.update_status,
            )
            self.vim.enter()
        else:
            self.vim = None
            area.read_only = False
            area.focus()

    # -------------------------------------------------------------------- keys
    def on_key(self, event: events.Key) -> None:
        """Vim NORMAL/VISUAL mode intercepts keys before the widget sees them."""
        if self.vim is not None and self.vim.mode != INSERT:
            if self.vim.handle_key(event.key):
                event.stop()
                event.prevent_default()
                self.update_status()

    def action_escape_key(self) -> None:
        """Escape: leave insert mode, leave the command bar, then go back."""
        if self.vim is not None and self.vim.mode == INSERT:
            self.vim.enter()
            self.update_status()
            return
        command = self.query_one("#command", Input)
        if command.has_focus:
            self.query_one("#editor", MarkdownArea).focus()
            return
        self.action_go_back()

    def _on_vim_search(self, prefix: str) -> None:
        self.action_focus_command(prefix)

    # ----------------------------------------------------------------- changes
    @on(MarkdownArea.Changed)
    def _changed(self, event: MarkdownArea.Changed) -> None:
        if self._loading:
            return
        # TextArea.Changed is delivered asynchronously, so compare against the
        # text that is known to be on disk instead of trusting a flag.
        area = self.query_one("#editor", MarkdownArea)
        self.dirty = area.text != self._saved_text
        self._last_change = time.time()
        self.update_status()

    @on(MarkdownArea.SelectionChanged)
    def _selection_changed(self, event: MarkdownArea.SelectionChanged) -> None:
        self.update_status()

    def _autosave_tick(self) -> None:
        if not self.dirty:
            return
        # Give the user a moment of quiet before writing to disk.
        if time.time() - self._last_change < 0.4:
            return
        self.save(silent=True)

    # -------------------------------------------------------------------- save
    def save(self, silent: bool = False) -> bool:
        """Persist the buffer, refresh the index and (optionally) auto-commit."""
        area = self.query_one("#editor", MarkdownArea)
        content = area.text
        try:
            note = self.store.update(self.ref, content)
        except StorageError as error:
            self.notify(f"save failed: {error}", severity="error")
            return False
        self.ref = note.ref
        self._saved_text = content
        self.dirty = False
        self.last_saved = time.time()
        self.sub_title = self.ref.title
        self.update_status()
        if not silent:
            self.notify(f"saved {self.ref.title}")
        self.app.auto_commit(self.ref)  # type: ignore[attr-defined]
        return True

    def update_status(self, message: str = "") -> None:
        area = self.query_one("#editor", MarkdownArea)
        text = area.text
        words = md.count_words(text)
        chars = md.count_chars(text)
        row, col = area.cursor_location
        tags = md.extract_tags(text)
        parts: list = [
            (f"{self.ref.title}", "bold"),
            (f"  {row + 1}:{col + 1}", "dim"),
            (f"  {words} words", ""),
            (f"  {chars} chars", "dim"),
        ]
        if tags:
            parts.append(("  " + " ".join(f"#{tag}" for tag in tags[:6]), "cyan"))
        if self.vim is not None:
            parts.append((f"  {self.vim.status_text()}", "bold magenta"))
        if message:
            parts.append((f"  {message}", "yellow"))
        elif self.dirty:
            parts.append(("  ● unsaved", "yellow"))
        elif self.last_saved:
            parts.append((f"  saved {time.strftime('%H:%M:%S', time.localtime(self.last_saved))}", "dim green"))
        elif self.ref.encrypted:
            parts.append(("  🔒 encrypted", "magenta"))
        self.query_one("#status", Static).update(Text.assemble(*parts))

    # ------------------------------------------------------------ command bar
    @on(Input.Submitted, "#command")
    def _command_submitted(self, event: Input.Submitted) -> None:
        value = event.value.strip()
        event.input.clear()
        if not value:
            return
        if value.startswith(":"):
            self.app.run_command(value[1:], context=self)  # type: ignore[attr-defined]
            return
        if self.vim is not None:
            self.vim.run_search(value)
        else:
            self._find_in_note(value)

    def _find_in_note(self, needle: str) -> None:
        area = self.query_one("#editor", MarkdownArea)
        offsets = md.find_occurrences(area.text, needle)
        if not offsets:
            self.notify(f'"{needle}" not found')
            return
        current = area.document.get_index_from_location(area.cursor_location)  # type: ignore[attr-defined]
        target = next((offset for offset in offsets if offset > current), offsets[0])
        area.move_cursor(md.location_of_offset(area.text, target), center=True)
        self.update_status(f"match {offsets.index(target) + 1}/{len(offsets)}")

    def action_focus_command(self, prefix: str = "") -> None:
        command = self.query_one("#command", Input)
        command.value = prefix
        command.focus()
        command.cursor_position = len(prefix)

    # ------------------------------------------------------------------ actions
    def action_save_note(self) -> None:
        self.save()

    def action_toggle_preview(self) -> None:
        self.save(silent=True)
        self.app.open_note(self.ref.path, mode="preview")  # type: ignore[attr-defined]

    def action_toggle_split(self) -> None:
        if self.emacs:
            raise SkipAction()  # let TextArea handle ctrl+e (end of line)
        self.save(silent=True)
        self.app.open_note(self.ref.path, mode="split")  # type: ignore[attr-defined]

    def action_show_backlinks(self) -> None:
        self.app.show_backlinks(self.ref)  # type: ignore[attr-defined]

    def action_show_graph(self) -> None:
        self.app.show_graph(self.ref)  # type: ignore[attr-defined]

    def action_new_note(self) -> None:
        self.save(silent=True)
        self.app.new_note()  # type: ignore[attr-defined]

    def action_add_tag(self) -> None:
        self.app.prompt(  # type: ignore[attr-defined]
            "Add tags to this note",
            value=" ".join(f"#{tag}" for tag in self.ref.tags),
            placeholder="#idea #reading",
            callback=self._apply_tags,
        )

    def _apply_tags(self, value: Optional[str]) -> None:
        if value is None:
            return
        tags = [token.lstrip("#") for token in value.split() if token.lstrip("#")]
        area = self.query_one("#editor", MarkdownArea)
        note = self.store.add_tags(self.ref, tags) if tags else None
        if note is None:
            return
        self._loading = True
        area.text = self.store.read_content(self.ref.path)
        self._loading = False
        self.ref = note.ref
        self.update_status()

    def action_toggle_numbers(self) -> None:
        area = self.query_one("#editor", MarkdownArea)
        area.show_line_numbers = not area.show_line_numbers
        self.app.config.editor.line_numbers = area.show_line_numbers  # type: ignore[attr-defined]
        self.notify(f"line numbers {'on' if area.show_line_numbers else 'off'}")

    def action_toggle_wrap(self) -> None:
        if self.emacs:
            raise SkipAction()  # let TextArea handle ctrl+w (delete word left)
        area = self.query_one("#editor", MarkdownArea)
        area.soft_wrap = not area.soft_wrap
        self.app.config.editor.soft_wrap = area.soft_wrap  # type: ignore[attr-defined]
        self.notify(f"soft wrap {'on' if area.soft_wrap else 'off'}")

    def action_show_help(self) -> None:
        extra = []
        if self.vim is not None:
            extra.append(("Vim normal mode", [(line.split(" — ")[0], line.split(" — ")[-1]) for line in self.vim.describe()]))
        self.app.show_help(extra)  # type: ignore[attr-defined]

    def action_page_up(self) -> None:
        if self._volume_keys_enabled():
            self.query_one("#editor", MarkdownArea).action_cursor_page_up()

    def action_page_down(self) -> None:
        if self._volume_keys_enabled():
            self.query_one("#editor", MarkdownArea).action_cursor_page_down()

    def _volume_keys_enabled(self) -> bool:
        config = getattr(self.app, "config", None)
        return bool(getattr(getattr(config, "termux", None), "volume_keys", True))

    def action_go_back(self) -> None:
        """Save, then return to the previous screen."""
        if self.dirty:
            if not self.save(silent=True):
                return
        self.app.back_to_list()  # type: ignore[attr-defined]

    @work(exclusive=True)
    async def reload_from_disk(self) -> None:
        content = self.store.read_content(self.ref.path)
        area = self.query_one("#editor", MarkdownArea)
        self._loading = True
        area.text = content
        self._loading = False
        self.dirty = False
        self.update_status()

    def on_resize(self, event: events.Resize) -> None:
        self.update_status()
