"""Graph view of ``[[linked]]`` notes (bonus challenge)."""

from __future__ import annotations

from typing import Optional

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Static

from tuinotes.graph import LinkGraph
from tuinotes.models import NoteRef
from tuinotes.storage import NoteStore


class GraphScreen(Screen):
    """ASCII link graph plus a navigable edge table."""

    BINDINGS = [
        Binding("escape", "go_back", "Back"),
        Binding("enter", "open_note", "Open"),
        Binding("question_mark", "show_help", "Help"),
    ]

    def __init__(
        self, store: NoteStore, focus: Optional[NoteRef] = None, *, depth: int = 2
    ) -> None:
        super().__init__()
        self.store = store
        self.focus_ref = focus
        self.depth = depth
        self.graph: Optional[LinkGraph] = None
        self._rows: dict = {}

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with VerticalScroll(id="graph-scroll"):
            yield Static("", id="graph", markup=False)
        yield DataTable(id="edges", cursor_type="row")
        yield Footer()

    def on_mount(self) -> None:
        graph = LinkGraph.build(self.store.all_refs())
        if self.focus_ref is not None:
            graph = graph.subgraph(self.focus_ref.path, depth=self.depth)
        self.graph = graph
        self.sub_title = "link graph"
        self.query_one("#graph", Static).update(
            graph.render_text(width=max(60, (self.size.width or 80) - 4))
        )
        stats = graph.stats()
        table = self.query_one("#edges", DataTable)
        table.add_columns("Note", "Links to", "Linked from")
        for path in sorted(graph.nodes):
            ref = graph.nodes[path]
            outgoing = ", ".join(graph.nodes[p].title for p in graph.outgoing(path)[:6]) or "—"
            incoming = ", ".join(graph.nodes[p].title for p in graph.backlinks(path)[:6]) or "—"
            table.add_row(ref.title, outgoing, incoming, key=path)
            self._rows[path] = table.row_count - 1
        self.notify(
            f"{stats['notes']} notes · {stats['links']} links · "
            f"{stats['clusters']} clusters · {stats['orphans']} unlinked"
        )
        if self.focus_ref is not None and self.focus_ref.path in self._rows:
            table.move_cursor(row=self._rows[self.focus_ref.path])
        table.focus()

    @on(DataTable.RowSelected)
    def _row_selected(self, event: DataTable.RowSelected) -> None:
        self.app.open_note(str(event.row_key.value), mode="edit")  # type: ignore[attr-defined]

    def action_open_note(self) -> None:
        table = self.query_one("#edges", DataTable)
        for path, index in self._rows.items():
            if index == table.cursor_row:
                self.app.open_note(path, mode="edit")  # type: ignore[attr-defined]
                return

    def action_go_back(self) -> None:
        self.app.back_to_list()  # type: ignore[attr-defined]

    def action_show_help(self) -> None:
        self.app.show_help()  # type: ignore[attr-defined]
