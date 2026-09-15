"""Command palette entries — ``:palette`` (or ``ctrl+\\``) for quick actions."""

from __future__ import annotations

from typing import TYPE_CHECKING, Iterable, cast

from textual.command import Hit, Hits, Provider

if TYPE_CHECKING:
    from tuinotes.tui.app import TuinotesApp


class TuinotesCommands(Provider):
    """Feeds the Textual command palette with note actions."""

    async def startup(self) -> None:  # pragma: no cover - Textual lifecycle
        return None

    async def search(self, query: str) -> Hits:
        # Matcher is built with the query; match(candidate) returns a float score
        # (0.0 == no match). `text` is set because match_display is a Content.
        matcher = self.matcher(query)
        for name, help_text, callback in self._entries():
            score = matcher.match(name)
            if score > 0:
                yield Hit(
                    score, matcher.highlight(name), callback, text=name, help=help_text
                )

    async def discover(self) -> Hits:
        for name, help_text, callback in self._entries():
            yield Hit(1.0, name, callback, help=help_text)

    def _entries(self) -> Iterable[tuple]:
        app = cast("TuinotesApp", self.app)
        yield ("new note", "Create a note", app.palette_new_note)
        yield ("daily note", "Open or create today's note", app.palette_daily_note)
        yield ("preview", "Preview the current note", app.palette_preview)
        yield ("split view", "Edit and preview side by side", app.palette_split)
        yield ("link graph", "Show the note graph", app.palette_graph)
        yield ("tags", "List tags with counts", app.palette_tags)
        yield ("trash", "Show deleted notes", app.palette_trash)
        yield ("reindex", "Rebuild the note index", app.palette_reindex)
        yield ("help", "Keybindings and commands", app.palette_help)
        yield ("save", "Save the current note", app.palette_save)
        for theme in getattr(app, "available_themes", ()):
            yield (f"theme: {theme}", "Switch theme", lambda name=theme: app.set_theme(name))
        for sort in ("modified", "newest", "oldest", "alphabetical", "size"):
            yield (f"sort: {sort}", "Sort the note list", lambda key=sort: app.set_sort(key))
        for template in app.template_names():
            yield (
                f"template: {template}",
                "New note from template",
                lambda name=template: app.new_note(template=name),
            )
