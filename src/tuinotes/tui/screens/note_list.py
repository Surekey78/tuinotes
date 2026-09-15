"""The main screen: searchable, tag-filterable, lazily paged note list."""

from __future__ import annotations

from typing import TYPE_CHECKING, List, Optional, Tuple, cast

from rich.text import Text
from textual import events, on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, DataTable, Footer, Header, Input, Static

from tuinotes.models import NoteRef, next_sort_key
from tuinotes.search import highlight, highlight_tags, parse_query
from tuinotes.storage import NoteStore

if TYPE_CHECKING:
    from tuinotes.tui.app import TuinotesApp


class TagChip(Button):
    """A tappable ``#tag`` filter chip."""

    DEFAULT_CSS = """
    TagChip { margin: 0 1 0 0; min-width: 4; height: 1; padding: 0 1; }
    TagChip.-active { background: $primary; color: $text; text-style: bold; }
    """

    def __init__(self, tag: str, count: int) -> None:
        # No widget id: the bar is rebuilt on every refresh and ids must stay unique.
        super().__init__(f"#{tag} {count}")
        self.tag = tag


class NoteListScreen(Screen):
    """List view — the screen you land on every time."""

    BINDINGS = [
        Binding("enter", "open_note", "Open"),
        Binding("n", "new_note", "New"),
        Binding("d", "delete_note", "Delete"),
        Binding("p", "preview_note", "Preview"),
        Binding("e", "split_note", "Split"),
        Binding("g", "show_graph", "Graph"),
        Binding("s", "cycle_sort", "Sort"),
        Binding("t", "filter_tags", "Tags"),
        Binding("r", "rename_note", "Rename"),
        Binding("/", "focus_search", "Search"),
        Binding("colon", "command_mode", "Command"),
        Binding("question_mark", "show_help", "Help"),
        Binding("j", "cursor_down", "", show=False),
        Binding("k", "cursor_up", "", show=False),
        Binding("q", "quit_app", "Quit"),
        Binding("ctrl+r", "reindex", "Reindex"),
        Binding("ctrl+t", "toggle_tag_bar", "Tag bar", show=False),
        Binding("ctrl+up", "page_up", "Page up", show=False),
        Binding("ctrl+down", "page_down", "Page down", show=False),
        Binding("ctrl+l", "toggle_lazy", "Load all", show=False),
    ]

    #: Start with the list focused so single-key actions work; ``/`` jumps to search.
    AUTO_FOCUS = "#notes"

    def __init__(self, store: NoteStore, sort: str = "modified", focus: Optional[str] = None) -> None:
        super().__init__()
        self.store = store
        self.sort = sort
        self.focus_note = focus
        self.search_query: str = ""
        self.tags: List[str] = []
        self._loaded = 0
        self._total = 0
        self._all_loaded = False
        self._refs: dict = {}
        self._columns: tuple = ("Note", "Preview", "Tags", "When")
        self._columns_changed = False

    # ------------------------------------------------------------------ layout
    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Vertical(id="top"):
            yield Input(
                placeholder="Search…  #tag  -#tag  in:folder  title:word  \"phrase\"",
                id="search",
            )
            with Horizontal(id="touchbar"):
                yield Button("New", id="btn-new", variant="success")
                yield Button("Open", id="btn-open", variant="primary")
                yield Button("Preview", id="btn-preview")
                yield Button("Split", id="btn-split")
                yield Button("Tags", id="btn-tags")
                yield Button("Sort", id="btn-sort")
                yield Button("Graph", id="btn-graph")
                yield Button("Help", id="btn-help")
            yield Horizontal(id="tagbar")
        yield DataTable(id="notes", cursor_type="row", zebra_stripes=True)
        yield Static("", id="status")
        yield Footer()

    async def on_mount(self) -> None:
        table = self.query_one("#notes", DataTable)
        table.add_columns(*self._columns_for_width(self.size.width or 80))
        self._columns = tuple(str(column.label) for column in table.ordered_columns)
        self.query_one("#search", Input).value = self.search_query
        self.load_notes(reset=True)

    # -------------------------------------------------------------------- data
    @property
    def page_size(self) -> int:
        config = getattr(self.app, "config", None)
        size = getattr(getattr(config, "list", None), "page_size", 100)
        return max(20, int(size))

    def load_notes(self, reset: bool = False) -> None:
        """(Re)populate the table, one page at a time."""
        table = self.query_one("#notes", DataTable)
        self._ensure_columns()
        if reset or self._columns_changed:
            table.clear(columns=False)
            self._refs = {}
            self._loaded = 0
            self._columns_changed = False
        refs = self.store.list_notes(
            sort=self.sort,
            tags=self.tags,
            query=self.search_query or None,
            limit=self.page_size,
            offset=self._loaded,
        )
        for ref in refs:
            self._add_row(ref)
            self._loaded += 1
        self._total = self.store.count(tags=self.tags) if not self.search_query else self._count_matches()
        self._render_tag_bar()
        self._update_status()
        if self.focus_note and self.focus_note in self._refs:
            table.move_cursor(row=self._refs[self.focus_note])
            self.focus_note = None
        elif reset and table.row_count:
            table.move_cursor(row=0)

    def _count_matches(self) -> int:
        return len(self.store.search(self.search_query, tags=self.tags, limit=0))

    def _add_row(self, ref: NoteRef) -> None:
        table = self.query_one("#notes", DataTable)
        needles = [token for token in parse_query(self.search_query).text.split() if token]
        title = highlight(ref.title, needles) if needles else Text(ref.title)
        if ref.encrypted:
            title = Text("🔒 ") + title
        elif ref.links:
            title = Text(f"↗{len(ref.links)} ") + title
        cells = {
            "Note": title,
            "Preview": highlight(ref.preview, needles) if needles else highlight_tags(ref.preview),
            "Tags": Text(" ".join(f"#{tag}" for tag in ref.tags[:4]), style="cyan"),
            "When": Text(ref.relative_time(), style="dim"),
        }
        table.add_row(*(cells[name] for name in self._columns), key=ref.path)
        self._refs[ref.path] = table.row_count - 1

    def _render_tag_bar(self) -> None:
        bar = self.query_one("#tagbar")
        bar.remove_children()
        counts = self.store.tag_counts()[:10]
        for tag, count in counts:
            chip = TagChip(tag, count)
            if tag.lower() in {t.lower() for t in self.tags}:
                chip.add_class("-active")
            bar.mount(chip)

    @staticmethod
    def _columns_for_width(width: int) -> Tuple[str, ...]:
        """Columns that fit the terminal: phones get title + date only."""
        if width < 70:
            return ("Note", "When")
        if width < 92:
            return ("Note", "Preview", "When")
        return ("Note", "Preview", "Tags", "When")

    def _ensure_columns(self) -> None:
        """Rebuild the table when the column set changes (DataTable cannot hide columns)."""
        table = self.query_one("#notes", DataTable)
        wanted = self._columns_for_width(self.size.width or 80)
        if wanted == self._columns:
            return
        table.clear(columns=True)
        table.add_columns(*wanted)
        self._columns = wanted
        self._columns_changed = True

    def _update_status(self, message: str = "") -> None:
        status = self.query_one("#status", Static)
        parts = [f"{self.store.count()} notes"]
        if self.search_query:
            parts.append(f"“{self.search_query}”")
        if self.tags:
            parts.append(" ".join(f"#{tag}" for tag in self.tags))
        parts.append(f"sort: {self.sort}")
        if self._loaded and self._loaded < self._total:
            parts.append(f"{self._loaded}/{self._total} loaded")
        parts.append("enter open · / search · n new · ? help")
        status.update(Text(" · ".join(parts) if not message else message, style="dim"))

    # ------------------------------------------------------------------ events
    @on(DataTable.RowSelected)
    def _row_selected(self, event: DataTable.RowSelected) -> None:
        self.open_path(str(event.row_key.value))

    @on(DataTable.RowHighlighted)
    def _row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        ref = self._ref_for_key(str(event.row_key.value))
        if ref:
            self.query_one("#status", Static).update(
                Text.assemble(
                    (ref.title, "bold"),
                    "  ",
                    (f"{ref.word_count} words · {ref.char_count} chars", "dim"),
                    "  ",
                    (ref.relative_time(), "dim"),
                    ("  " + ref.tag_str if ref.tag_str else "", "cyan"),
                )
            )
        table = self.query_one("#notes", DataTable)
        if not self._all_loaded and table.row_count and event.cursor_row >= table.row_count - 3:
            self.load_notes()

    @on(Input.Changed, "#search")
    def _search_changed(self, event: Input.Changed) -> None:
        self.set_timer(0.12, self._apply_search)

    def _apply_search(self) -> None:
        value = self.query_one("#search", Input).value
        if value == self.search_query:
            return
        self.search_query = value
        self.load_notes(reset=True)

    @on(Input.Submitted, "#search")
    def _search_submitted(self, event: Input.Submitted) -> None:
        """Enter in the search box opens the best match (handy on a phone)."""
        self.search_query = event.value
        self.load_notes(reset=True)
        table = self.query_one("#notes", DataTable)
        table.focus()
        if table.row_count:
            self.action_open_note()

    @on(Button.Pressed, "#touchbar")
    def _touch(self, event: Button.Pressed) -> None:
        action = {
            "btn-new": self.action_new_note,
            "btn-open": self.action_open_note,
            "btn-preview": self.action_preview_note,
            "btn-split": self.action_split_note,
            "btn-tags": self.action_filter_tags,
            "btn-sort": self.action_cycle_sort,
            "btn-graph": self.action_show_graph,
            "btn-help": self.action_show_help,
        }.get(event.button.id or "")
        if action:
            action()

    @on(Button.Pressed)
    def _chip(self, event: Button.Pressed) -> None:
        if not isinstance(event.button, TagChip):
            return
        tag = event.button.tag
        if tag in self.tags:
            self.tags.remove(tag)
        else:
            self.tags.append(tag)
        self.load_notes(reset=True)

    def on_resize(self, event: events.Resize) -> None:
        self.load_notes(reset=True)

    def on_screen_resume(self, event: events.ScreenResume) -> None:
        """Refresh whenever we come back from the editor."""
        self.refresh_notes(keep_cursor=True)

    # ------------------------------------------------------------------ actions
    def refresh_notes(self, keep_cursor: bool = False) -> None:
        table = self.query_one("#notes", DataTable)
        current = str(table.cursor_row) if keep_cursor else None
        highlighted = self._key_at_cursor()
        self.load_notes(reset=True)
        if keep_cursor and highlighted and highlighted in self._refs:
            table.move_cursor(row=self._refs[highlighted])
        del current

    def _key_at_cursor(self) -> Optional[str]:
        table = self.query_one("#notes", DataTable)
        if not table.row_count:
            return None
        for path, index in self._refs.items():
            if index == table.cursor_row:
                return path
        return None

    def _ref_for_key(self, key: str) -> Optional[NoteRef]:
        try:
            return self.store._ref_for(key)  # noqa: SLF001 - same package
        except Exception:
            return None

    def selected_ref(self) -> Optional[NoteRef]:
        key = self._key_at_cursor()
        return self._ref_for_key(key) if key else None

    def open_path(self, path: str) -> None:
        self.app.open_note(path, mode="edit")  # type: ignore[attr-defined]

    def action_open_note(self) -> None:
        ref = self.selected_ref()
        if ref:
            self.open_path(ref.path)

    def action_new_note(self) -> None:
        self.app.new_note()  # type: ignore[attr-defined]

    def action_preview_note(self) -> None:
        ref = self.selected_ref()
        if ref:
            self.app.open_note(ref.path, mode="preview")  # type: ignore[attr-defined]

    def action_split_note(self) -> None:
        ref = self.selected_ref()
        if ref:
            self.app.open_note(ref.path, mode="split")  # type: ignore[attr-defined]

    def action_delete_note(self) -> None:
        ref = self.selected_ref()
        if ref:
            self.app.delete_note(ref)  # type: ignore[attr-defined]

    def action_rename_note(self) -> None:
        ref = self.selected_ref()
        if ref:
            self.app.rename_note(ref)  # type: ignore[attr-defined]

    def action_show_graph(self) -> None:
        self.app.show_graph()  # type: ignore[attr-defined]

    def action_cycle_sort(self) -> None:
        self.sort = next_sort_key(self.sort)
        self.load_notes(reset=True)
        self.notify(f"sort: {self.sort}")

    def action_filter_tags(self) -> None:
        tags = [tag for tag, _ in self.store.tag_counts()[:40]]
        self.app.prompt(  # type: ignore[attr-defined]
            "Filter by tags (space separated, prefix - to exclude)",
            value=" ".join(f"#{tag}" for tag in self.tags),
            placeholder=" ".join(f"#{tag}" for tag in tags[:8]),
            callback=self._apply_tag_filter,
        )

    def _apply_tag_filter(self, value: Optional[str]) -> None:
        if value is None:
            return
        self.tags = [token.lstrip("#") for token in value.split() if token.lstrip("#")]
        self.load_notes(reset=True)

    def action_focus_search(self) -> None:
        self.query_one("#search", Input).focus()

    def action_toggle_tag_bar(self) -> None:
        self.query_one("#tagbar").toggle_class("-hidden")

    def action_toggle_lazy(self) -> None:
        """Load every row (useful before exporting the whole vault)."""
        self._all_loaded = True
        while True:
            before = self._loaded
            self.load_notes()
            if self._loaded == before:
                break
        self._update_status()
        self.notify(f"{self._loaded} notes loaded")

    def action_command_mode(self) -> None:
        self.app.command_mode()  # type: ignore[attr-defined]

    def action_show_help(self) -> None:
        self.app.show_help()  # type: ignore[attr-defined]

    def action_reindex(self) -> None:
        self.notify("reindexing…")
        self._reindex_worker()

    @work(thread=True, exclusive=True)
    def _reindex_worker(self) -> None:
        count = self.store.reindex()
        self.app.call_from_thread(self.load_notes, True)
        self.app.call_from_thread(self.notify, f"indexed {count} notes")

    def action_cursor_down(self) -> None:
        self.query_one("#notes", DataTable).action_cursor_down()

    def action_cursor_up(self) -> None:
        self.query_one("#notes", DataTable).action_cursor_up()

    def action_page_up(self) -> None:
        if self._volume_keys_enabled():
            self.query_one("#notes", DataTable).action_page_up()

    def action_page_down(self) -> None:
        if self._volume_keys_enabled():
            self.query_one("#notes", DataTable).action_page_down()

    def _volume_keys_enabled(self) -> bool:
        config = getattr(self.app, "config", None)
        return bool(getattr(getattr(config, "termux", None), "volume_keys", True))

    def action_quit_app(self) -> None:
        cast("TuinotesApp", self.app).action_quit_app()

    def key_escape(self) -> None:
        search = self.query_one("#search", Input)
        if search.has_focus and (search.value or self.search_query):
            search.value = ""
            self.search_query = ""
            self.load_notes(reset=True)
            return
        self.query_one("#notes", DataTable).focus()
