"""TUI behaviour, driven through Textual's pilot."""

from __future__ import annotations

from textual.widgets import DataTable, Input

from tuinotes.tui.app import TuinotesApp
from tuinotes.tui.dialogs import ConfirmScreen, HelpScreen, PromptScreen
from tuinotes.tui.markdown_area import MarkdownArea
from tuinotes.tui.screens.editor import EditorScreen
from tuinotes.tui.screens.graph import GraphScreen
from tuinotes.tui.screens.note_list import NoteListScreen
from tuinotes.tui.screens.preview import PreviewScreen
from tuinotes.tui.screens.split import SplitScreen

SIZE = (100, 32)


def table(app) -> DataTable:
    return app.screen.query_one("#notes", DataTable)


def editor(app) -> MarkdownArea:
    return app.screen.query_one("#editor", MarkdownArea)


async def open_first_note(pilot, app):
    await pilot.pause()
    await pilot.press("enter")
    await pilot.pause()
    assert isinstance(app.screen, EditorScreen)


# ------------------------------------------------------------------- the list
async def test_list_screen_shows_the_vault(seeded):
    app = TuinotesApp(seeded, seeded.config)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        assert isinstance(app.screen, NoteListScreen)
        assert table(app).row_count == 3
        assert app.theme == "tuinotes-dark"


async def test_search_filters_the_list(seeded):
    app = TuinotesApp(seeded, seeded.config)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        await pilot.press("/")  # focus the search box
        await pilot.press(*"grocer")
        await pilot.pause(0.4)  # debounce
        assert table(app).row_count == 1
        await pilot.press("escape")
        await pilot.pause()
        assert table(app).row_count == 3


async def test_tag_syntax_filters_the_list(seeded):
    app = TuinotesApp(seeded, seeded.config)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        await pilot.press("/")
        await pilot.press(*"#rust")
        await pilot.pause(0.4)
        assert table(app).row_count == 2


async def test_sort_cycles(seeded):
    app = TuinotesApp(seeded, seeded.config)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        assert app.screen.sort == "modified"
        await pilot.press("s")
        await pilot.pause()
        assert app.screen.sort == "newest"


async def test_new_note_flow(seeded, tmp_path):
    app = TuinotesApp(seeded, seeded.config)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        await pilot.press("n")
        await pilot.pause()
        assert isinstance(app.screen, PromptScreen)
        prompt = app.screen.query_one("#answer", Input)
        prompt.value = "Fresh note"
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, EditorScreen)
        assert app.screen.ref.title == "Fresh note"
        assert (seeded.root / app.screen.ref.path).is_file()


async def test_delete_asks_first(seeded):
    app = TuinotesApp(seeded, seeded.config)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        await pilot.press("d")
        await pilot.pause()
        assert isinstance(app.screen, ConfirmScreen)
        await pilot.press("y")
        await pilot.pause()
        assert isinstance(app.screen, NoteListScreen)
        assert table(app).row_count == 2
        assert seeded.list_trash()


# ------------------------------------------------------------------- editor
async def test_editor_loads_the_note(seeded):
    app = TuinotesApp(seeded, seeded.config)
    async with app.run_test(size=SIZE) as pilot:
        await open_first_note(pilot, app)
        assert editor(app).text.startswith("# ")
        assert app.screen.dirty is False


async def test_typing_marks_dirty_and_ctrl_s_saves(seeded):
    app = TuinotesApp(seeded, seeded.config)
    async with app.run_test(size=SIZE) as pilot:
        await open_first_note(pilot, app)
        await pilot.press(*"appended")
        await pilot.pause()
        assert app.screen.dirty is True
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert app.screen.dirty is False
        body = seeded.read_content(app.screen.ref.path)
        assert "appended" in body


async def test_autosave_writes_without_an_explicit_save(seeded):
    seeded.config.editor.autosave_interval = 0.2
    app = TuinotesApp(seeded, seeded.config)
    async with app.run_test(size=SIZE) as pilot:
        await open_first_note(pilot, app)
        await pilot.press(*"autosaved")
        await pilot.pause(1.0)  # longer than the autosave interval
        body = seeded.read_content(app.screen.ref.path)
        assert "autosaved" in body
        assert app.screen.dirty is False


async def test_command_bar_saves_and_goes_back(seeded):
    app = TuinotesApp(seeded, seeded.config)
    async with app.run_test(size=SIZE) as pilot:
        await open_first_note(pilot, app)
        app.screen.action_focus_command(":w")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert app.screen.dirty is False

        app.screen.action_focus_command(":q")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, NoteListScreen)


async def test_command_bar_adds_a_tag(seeded):
    app = TuinotesApp(seeded, seeded.config)
    async with app.run_test(size=SIZE) as pilot:
        await open_first_note(pilot, app)
        app.screen.action_focus_command(":tag idea")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert "idea" in seeded.resolve(app.screen.ref.path).tags


async def test_command_bar_reports_unknown_commands(seeded):
    app = TuinotesApp(seeded, seeded.config)
    async with app.run_test(size=SIZE) as pilot:
        await open_first_note(pilot, app)
        app.screen.action_focus_command(":wrtie")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert app.screen.query_one("#command", Input).value == ""


async def test_status_bar_counts_words(seeded):
    app = TuinotesApp(seeded, seeded.config)
    async with app.run_test(size=SIZE) as pilot:
        await open_first_note(pilot, app)
        status = str(app.screen.query_one("#status").render())
        assert "words" in status and "chars" in status


# --------------------------------------------------------------- vim keymap
async def test_vim_normal_mode_moves_and_deletes(seeded):
    seeded.config.editor.keymap = "vim"
    app = TuinotesApp(seeded, seeded.config)
    async with app.run_test(size=SIZE) as pilot:
        await open_first_note(pilot, app)
        area = editor(app)
        assert app.screen.vim is not None
        assert area.read_only is True  # NORMAL mode hands keys to VimMode
        assert app.screen.vim.status_text() == "NORMAL"

        await pilot.press("j", "j")  # down to "- [ ] milk"
        await pilot.pause()
        assert area.cursor_location[0] == 2

        await pilot.press("i")  # insert mode gives the widget back
        await pilot.pause()
        assert area.read_only is False
        assert app.screen.vim.mode == "insert"

        await pilot.press("escape")
        await pilot.pause()
        assert area.read_only is True

        before = area.text
        await pilot.press("x")  # delete the character under the cursor
        await pilot.pause()
        assert area.text != before
        assert len(area.text) == len(before) - 1


async def test_vim_dd_removes_a_line(seeded):
    seeded.config.editor.keymap = "vim"
    app = TuinotesApp(seeded, seeded.config)
    async with app.run_test(size=SIZE) as pilot:
        await open_first_note(pilot, app)
        area = editor(app)
        lines_before = area.document.line_count
        await pilot.press("d", "d")
        await pilot.pause()
        assert area.document.line_count == lines_before - 1
        assert app.screen.vim.register  # the deleted line is yanked


# ------------------------------------------------------- preview/split/graph
async def test_preview_screen_renders_markdown(seeded):
    app = TuinotesApp(seeded, seeded.config)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        await pilot.press("p")
        await pilot.pause()
        assert isinstance(app.screen, PreviewScreen)
        await pilot.press("e")
        await pilot.pause()
        assert isinstance(app.screen, EditorScreen)


async def test_split_screen_stacks_when_narrow(seeded):
    app = TuinotesApp(seeded, seeded.config)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        await pilot.press("e")
        await pilot.pause()
        assert isinstance(app.screen, SplitScreen)
        assert app.screen.query_one("#panes").layout.name == "horizontal"
        await pilot.resize_terminal(40, 30)
        await pilot.pause()
        assert app.screen.query_one("#panes").layout.name == "vertical"


async def test_split_screen_saves(seeded):
    app = TuinotesApp(seeded, seeded.config)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        await pilot.press("e")
        await pilot.pause()
        await pilot.press(*"splitnote")
        await pilot.pause()
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert "splitnote" in seeded.read_content(app.screen.ref.path)


async def test_graph_screen_opens(seeded):
    app = TuinotesApp(seeded, seeded.config)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        await pilot.press("g")
        await pilot.pause()
        assert isinstance(app.screen, GraphScreen)
        assert "Tokio" in str(app.screen.query_one("#graph").render())


async def test_help_screen_lists_keys(seeded):
    app = TuinotesApp(seeded, seeded.config)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        await pilot.press("question_mark")
        await pilot.pause()
        assert isinstance(app.screen, HelpScreen)
        await pilot.press("escape")
        await pilot.pause()
        assert isinstance(app.screen, NoteListScreen)


# ------------------------------------------------------------------ markdown
def test_builtin_highlighter_spans_a_heading():
    from tuinotes.tui.markdown_area import _scan

    spans = _scan("# Title\n\nSome **bold** and `code` #tag [[Link]]\n```\nfenced\n```")
    assert any(name == "heading" for _, _, name in spans[0])
    names = {name for _, _, name in spans[2]}
    assert {"bold", "inline_code", "keyword", "type"} <= names
    assert any(name == "inline_code" for _, _, name in spans[4])


def test_builtin_highlighter_uses_byte_offsets():
    from tuinotes.tui.markdown_area import _scan

    # Highlight spans are UTF-8 byte offsets, so they must decode cleanly.
    line = "# café ☕"
    spans = _scan(line + "\n")
    heading = [span for span in spans[0] if span[2] == "heading"]
    assert heading
    start, end, _ = heading[0]
    encoded = line.encode("utf-8")
    assert encoded[start:end].decode("utf-8") == "café ☕"


async def test_emacs_keymap_gives_ctrl_e_to_the_widget(seeded):
    """In emacs mode ctrl+e moves to end of line instead of opening the split."""
    seeded.config.editor.keymap = "emacs"
    app = TuinotesApp(seeded, seeded.config)
    async with app.run_test(size=SIZE) as pilot:
        await open_first_note(pilot, app)
        area = editor(app)
        area.move_cursor((2, 0))
        await pilot.pause()
        await pilot.press("ctrl+e")
        await pilot.pause()
        assert isinstance(app.screen, EditorScreen)  # no split screen
        assert area.cursor_location[0] == 2
        assert area.cursor_location[1] > 0  # jumped to the end of the line


async def test_ctrl_arrows_page_the_list(seeded):
    app = TuinotesApp(seeded, seeded.config)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        table_widget = table(app)
        before = table_widget.cursor_row
        await pilot.press("ctrl+down")
        await pilot.pause()
        # Nothing to page to with three rows, but the binding must not error and
        # must keep the cursor inside the table.
        assert 0 <= table_widget.cursor_row < table_widget.row_count
        assert table_widget.cursor_row >= before


async def test_columns_adapt_to_terminal_width(seeded):
    """Narrow terminals drop columns instead of squashing them (phones)."""
    app = TuinotesApp(seeded, seeded.config)
    async with app.run_test(size=(100, 32)) as pilot:
        await pilot.pause()
        assert [str(c.label) for c in table(app).ordered_columns] == [
            "Note",
            "Preview",
            "Tags",
            "When",
        ]
        await pilot.resize_terminal(50, 32)
        await pilot.pause()
        assert [str(c.label) for c in table(app).ordered_columns] == ["Note", "When"]
        assert table(app).row_count == 3  # rows are rebuilt, not lost


async def test_reindex_from_the_list_screen(seeded):
    """ctrl+r reindexes in a worker thread without touching the UI directly."""
    app = TuinotesApp(seeded, seeded.config)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        await pilot.press("ctrl+r")
        await pilot.pause(0.5)
        assert table(app).row_count == 3
        assert seeded.count() == 3


async def test_command_palette_searches_commands(seeded):
    """The palette must open and fuzzy-match our commands (matcher API)."""
    app = TuinotesApp(seeded, seeded.config)
    async with app.run_test(size=SIZE) as pilot:
        await open_first_note(pilot, app)
        app.screen.action_focus_command(":palette")
        await pilot.press("enter")
        await pilot.pause()
        assert app.screen.__class__.__name__ == "CommandPalette"

        await pilot.press(*"ren")
        await pilot.pause(0.3)
        options = app.screen.query_one("CommandList").options
        texts = [option.hit.text or "" for option in options]
        assert "reindex" in texts
        assert any("theme:" in text for text in texts)

        # picking a hit runs its callback
        await pilot.press("ctrl+u")  # clear the input
        await pilot.press(*"graph")
        await pilot.pause(0.3)
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, GraphScreen)
