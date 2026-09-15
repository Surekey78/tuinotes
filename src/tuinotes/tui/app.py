"""The Textual application: screens, keybindings and the ``:command`` dispatch."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Callable, List, Optional

from textual import work
from textual.app import App
from textual.binding import Binding
from textual.theme import Theme
from textual.widgets import Input

from tuinotes import __version__, exporter, termux, themes
from tuinotes.commands import parse_command
from tuinotes.config import Config
from tuinotes.git_sync import GitError, from_config
from tuinotes.models import NoteRef
from tuinotes.storage import NoteNotFound, NoteStore, StorageError
from tuinotes.tui.dialogs import ConfirmScreen, HelpScreen, MessageScreen, PromptScreen
from tuinotes.tui.markdown_area import MarkdownArea
from tuinotes.tui.palette import TuinotesCommands
from tuinotes.tui.screens.editor import EditorScreen
from tuinotes.tui.screens.graph import GraphScreen
from tuinotes.tui.screens.note_list import NoteListScreen
from tuinotes.tui.screens.preview import PreviewScreen
from tuinotes.tui.screens.split import SplitScreen

NOTE_SCREENS = (EditorScreen, PreviewScreen, SplitScreen)


class TuinotesApp(App):
    """The whole interface: a note list plus editor/preview/split/graph screens."""

    CSS_PATH = "tuinotes.tcss"
    TITLE = "tuinotes"
    SUB_TITLE = f"v{__version__}"
    COMMANDS = {TuinotesCommands}  # type: ignore[assignment]

    BINDINGS = [
        Binding("ctrl+q", "quit", "Quit", priority=True),
        Binding("ctrl+n", "app_new_note", "New", priority=True),
        Binding("f1", "app_help", "Help", priority=True),
        Binding("ctrl+backslash", "command_palette", "Commands", priority=True),
        Binding("ctrl+shift+t", "cycle_theme", "Theme", priority=True, show=False),
    ]

    def __init__(
        self,
        store: NoteStore,
        config: Config,
        *,
        initial_note: Optional[str] = None,
        initial_mode: str = "edit",
    ) -> None:
        super().__init__()
        self.store = store
        self.config = config
        self.git = from_config(config)
        self.initial_note = initial_note
        self.initial_mode = initial_mode
        self.list_screen: Optional[NoteListScreen] = None
        self._startup_done = False

    # -------------------------------------------------------------------- boot
    def on_mount(self) -> None:
        themes.register(self)
        self._apply_theme(self.config.theme, notify=False)
        self.list_screen = NoteListScreen(
            self.store, sort=self.config.list.sort, focus=self.initial_note
        )
        self.push_screen(self.list_screen)
        if self.initial_note:
            mode = self.initial_mode if self.initial_mode != "list" else "edit"
            self.open_note(self.initial_note, mode=mode)
        self._startup_tasks()

    @work(thread=True, exclusive=True)
    def _startup_tasks(self) -> None:
        """Housekeeping that must not block the first frame."""
        messages: List[str] = []
        try:
            purged = self.store.purge_trash()
            if purged:
                messages.append(f"purged {purged} old note(s) from trash")
        except StorageError:
            pass
        if self.config.termux.keep_awake and termux.is_termux():
            termux.wake_lock(True)
        if self.config.git.enabled and self.config.git.pull_on_start:
            try:
                messages.append(f"git: {self.git.pull()}")
            except GitError as error:
                messages.append(f"git pull failed: {error}")
        elif self.config.git.enabled:
            try:
                status = self.git.status()
                if status.is_repo:
                    messages.append(f"git: {status.describe()}")
            except GitError:
                pass
        for message in messages:
            self.call_from_thread(self.notify, message)
        self._startup_done = True

    # ----------------------------------------------------------------- theming
    def _apply_theme(self, name: str, *, notify: bool = True) -> None:
        available = set(getattr(self, "available_themes", ()))
        if name not in available:
            name = "textual-dark"
        self.theme = name
        self.config.theme = name
        if notify:
            self.notify(f"theme: {name}")

    def set_theme(self, name: str) -> None:
        self._apply_theme(name)

    def action_cycle_theme(self) -> None:
        names = list(getattr(self, "available_themes", ())) or ["textual-dark"]
        index = (names.index(self.theme) + 1) % len(names) if self.theme in names else 0
        self._apply_theme(names[index])

    # -------------------------------------------------------------- navigation
    def open_note(self, needle: str, mode: str = "edit") -> None:
        """Open a note by path, stem or title in the requested mode."""
        try:
            ref = self._resolve(needle)
        except NoteNotFound as error:
            self.notify(str(error), severity="error")
            return
        current = self.screen
        if isinstance(current, NOTE_SCREENS):
            if type(current) is self._screen_class(mode) and current.ref.path == ref.path:
                return
            self.pop_screen()
        screen = self._screen_class(mode)(self.store, ref)
        self.push_screen(screen)

    @staticmethod
    def _screen_class(mode: str):
        return {
            "edit": EditorScreen,
            "preview": PreviewScreen,
            "split": SplitScreen,
        }.get(mode, EditorScreen)

    def _resolve(self, needle: str) -> NoteRef:
        if isinstance(needle, NoteRef):
            return needle
        return self.store.resolve(needle)

    def back_to_list(self) -> None:
        """Pop back to the note list and refresh it."""
        for _ in range(len(self.screen_stack)):
            if isinstance(self.screen, NoteListScreen):
                break
            self.pop_screen()
        if isinstance(self.screen, NoteListScreen):
            self.screen.refresh_notes(keep_cursor=True)
            self.screen.query_one("#notes").focus()

    def new_note(
        self, template: Optional[str] = None, title: Optional[str] = None, content: str = ""
    ) -> None:
        """Create a note (prompting for a title unless one is supplied)."""
        if title is None and template is None and not content:
            self.prompt(
                "New note title (leave empty for a quick capture)",
                placeholder="Shopping list, Idea, Meeting with …",
                callback=lambda value: self._create_note(value or None, template, content),
            )
            return
        self._create_note(title, template, content)

    def _create_note(
        self, title: Optional[str], template: Optional[str] = None, content: str = ""
    ) -> None:
        try:
            note = self.store.create(title=title, template=template, content=content)
        except (StorageError, KeyError) as error:
            self.notify(f"could not create note: {error}", severity="error")
            return
        self.notify(f"created {note.ref.title}")
        self.open_note(note.path, mode="edit")

    def delete_note(self, ref: NoteRef) -> None:
        days = self.config.trash.retention_days
        self.confirm(
            f"Delete “{ref.title}”?\nIt stays in .trash for {days} days.",
            lambda yes: self._delete_note(ref, yes),
        )

    def _delete_note(self, ref: NoteRef, confirmed: bool) -> None:
        if not confirmed:
            return
        try:
            self.store.delete(ref)
        except StorageError as error:
            self.notify(f"delete failed: {error}", severity="error")
            return
        self.notify(f"moved {ref.title} to trash")
        if isinstance(self.screen, NOTE_SCREENS):
            self.back_to_list()
        elif isinstance(self.screen, NoteListScreen):
            self.screen.refresh_notes()

    def rename_note(self, ref: NoteRef) -> None:
        self.prompt(
            "Rename note",
            value=ref.title,
            callback=lambda value: self._rename_note(ref, value),
        )

    def _rename_note(self, ref: NoteRef, value: Optional[str]) -> None:
        if not value or value.strip() == ref.title:
            return
        try:
            note = self.store.rename(ref, value.strip())
        except StorageError as error:
            self.notify(f"rename failed: {error}", severity="error")
            return
        self.notify(f"renamed to {note.ref.title}")
        if isinstance(self.screen, (EditorScreen, SplitScreen)):
            self.screen.ref = note.ref
            self.screen.update_status()
        self._refresh_list()

    def _refresh_list(self) -> None:
        if isinstance(self.screen, NoteListScreen):
            self.screen.refresh_notes(keep_cursor=True)
        elif self.list_screen is not None:
            self.list_screen.refresh_notes(keep_cursor=True)

    # ------------------------------------------------------------------ dialogs
    def confirm(
        self, question: str, callback: Callable[[bool], None], confirm_label: str = "Yes"
    ) -> None:
        self.push_screen(
            ConfirmScreen(question, confirm_label=confirm_label),
            lambda result: callback(bool(result)),
        )

    def prompt(
        self,
        question: str,
        value: str = "",
        placeholder: str = "",
        callback: Optional[Callable[[Optional[str]], None]] = None,
    ) -> None:
        def done(result: Optional[str]) -> None:
            if callback is not None:
                callback(result)

        self.push_screen(
            PromptScreen(question, value, placeholder=placeholder), done
        )

    def command_mode(self, prefix: str = ":") -> None:
        """``:`` command mode for the note list (the editor has its own bar)."""
        self.prompt(
            "Command",
            value=prefix,
            placeholder=":daily · :tag idea · :sort newest · :export html",
            callback=lambda value: self.run_command(value or "") if value else None,
        )

    def show_help(self, extra: Optional[List[tuple]] = None) -> None:
        self.push_screen(HelpScreen(extra=extra))

    def show_backlinks(self, ref: NoteRef) -> None:
        incoming = self.store.backlinks(ref)
        outgoing = self.store.outgoing(ref)
        rows = [(item.title, "links here") for item in incoming]
        rows += [
            (link, f"→ {target.title}" if target else "→ missing note")
            for link, target in outgoing
        ]
        body = (
            f"“{ref.title}”\n\n"
            f"{len(incoming)} note(s) link here, {len(outgoing)} outgoing link(s)."
        )
        self.push_screen(MessageScreen("Backlinks & links", body, rows=rows))

    def show_graph(self, focus: Optional[NoteRef] = None) -> None:
        self.push_screen(GraphScreen(self.store, focus))

    def show_trash(self) -> None:
        entries = self.store.list_trash()
        rows = [
            (entry.title, f"{entry.original_path} · deleted {entry.relative_time()}")
            for entry in entries
        ]
        body = "Trash is empty." if not rows else f"{len(rows)} note(s) in .trash"
        self.push_screen(MessageScreen("Trash", body, rows=rows))

    def show_tags(self) -> None:
        counts = self.store.tag_counts()
        rows = [(f"#{tag}", f"{count} note(s)") for tag, count in counts]
        body = "No tags yet — add #hashtags inside your notes." if not rows else ""
        self.push_screen(MessageScreen("Tags", body, rows=rows))

    # ---------------------------------------------------------------- commands
    def run_command(self, line: str, context=None) -> None:
        """Execute a ``:command`` line (see :mod:`tuinotes.commands`)."""
        parsed = parse_command(line)
        if not parsed.ok:
            self.notify(parsed.error, severity="error", timeout=6)
            return
        name, args = parsed.name, parsed.args
        handler = getattr(self, f"_cmd_{name}", None)
        if handler is None:
            self.notify(f":{name} is not available here", severity="error")
            return
        try:
            handler(args, context)
        except (StorageError, NoteNotFound, GitError, exporter.ExportError) as error:
            self.notify(f":{name} failed: {error}", severity="error", timeout=8)

    # -- command implementations ---------------------------------------------
    def _current_ref(self, context=None) -> Optional[NoteRef]:
        screen = context or self.screen
        ref = getattr(screen, "ref", None)
        if isinstance(ref, NoteRef):
            return ref
        if isinstance(self.screen, NoteListScreen):
            return self.screen.selected_ref()
        return None

    def _save_current(self, context=None) -> bool:
        screen = context or self.screen
        if hasattr(screen, "save"):
            return bool(screen.save(silent=True))
        return False

    def _cmd_palette(self, args, context) -> None:
        """``:palette`` — open the fuzzy command palette."""
        self.action_command_palette()

    def _cmd_w(self, args, context) -> None:
        if self._save_current(context):
            self.notify("saved")

    _cmd_write = _cmd_w

    def _cmd_q(self, args, context) -> None:
        if isinstance(self.screen, NoteListScreen) and len(self.screen_stack) == 1:
            self.action_quit_app()
        else:
            self.back_to_list()

    def _cmd_quit(self, args, context) -> None:
        self.action_quit_app()

    def _cmd_wq(self, args, context) -> None:
        self._save_current(context)
        self.back_to_list()

    def _cmd_n(self, args, context) -> None:
        self.new_note(title=" ".join(args) or None)

    def _cmd_e(self, args, context) -> None:
        if not args:
            self.back_to_list()
            return
        self.open_note(" ".join(args), mode="edit")

    def _cmd_d(self, args, context) -> None:
        ref = self._resolve(" ".join(args)) if args else self._current_ref(context)
        if ref is None:
            self.notify("no note selected")
            return
        self.delete_note(ref)

    _cmd_delete = _cmd_d

    def _cmd_restore(self, args, context) -> None:
        entries = self.store.list_trash()
        if not entries:
            self.notify("trash is empty")
            return
        needle = " ".join(args).lower()
        match = next(
            (
                entry
                for entry in entries
                if not needle
                or needle in entry.title.lower()
                or needle in entry.original_path.lower()
            ),
            None,
        )
        if match is None:
            self.show_trash()
            return
        ref = self.store.restore(match.path)
        self.notify(f"restored {ref.title}")
        self._refresh_list()

    def _cmd_s(self, args, context) -> None:
        query = " ".join(args)
        if not isinstance(self.screen, NoteListScreen):
            self.back_to_list()
        if isinstance(self.screen, NoteListScreen):
            self.screen.query_one("#search", Input).value = query
            self.screen.search_query = query
            self.screen.load_notes(reset=True)

    _cmd_search = _cmd_s

    def _cmd_tag(self, args, context) -> None:
        ref = self._current_ref(context)
        if ref is None:
            self.notify("open a note first")
            return
        tags = [arg.lstrip("#") for arg in args if arg.lstrip("#")]
        note = self.store.add_tags(ref, tags)
        self._reload_editor(context, note.ref)
        self.notify(f"tags: {note.ref.tag_str or 'none'}")

    def _cmd_untag(self, args, context) -> None:
        ref = self._current_ref(context)
        if ref is None:
            self.notify("open a note first")
            return
        tags = [arg.lstrip("#") for arg in args if arg.lstrip("#")]
        note = self.store.remove_tags(ref, tags)
        self._reload_editor(context, note.ref)
        self.notify(f"tags: {note.ref.tag_str or 'none'}")

    def _reload_editor(self, context, ref: NoteRef) -> None:
        screen = context or self.screen
        if isinstance(screen, (EditorScreen, SplitScreen)):
            screen.ref = ref
            screen._loading = True
            screen.query_one("#editor", MarkdownArea).text = self.store.read_content(ref.path)
            screen._loading = False
            screen.dirty = False
            screen.update_status()
        self._refresh_list()

    def _cmd_tags(self, args, context) -> None:
        self.show_tags()

    def _cmd_sort(self, args, context) -> None:
        self.set_sort(args[0] if args else "modified")

    def _cmd_theme(self, args, context) -> None:
        if not args:
            self.action_cycle_theme()
            return
        self._apply_theme(" ".join(args))

    def _cmd_daily(self, args, context) -> None:
        note = self.store.daily_note(template=args[0] if args else None)
        self.notify(f"daily note: {note.ref.title}")
        self.open_note(note.path, mode="edit")

    def _cmd_template(self, args, context) -> None:
        if not args:
            self.notify("usage: :template <name> (:templates to list)")
            return
        self.new_note(template=args[0], title=" ".join(args[1:]) or None)

    def _cmd_templates(self, args, context) -> None:
        from tuinotes.templates import describe

        rows = [(name, describe(name, self.config)) for name in self.template_names()]
        self.push_screen(MessageScreen("Templates", "", rows=rows))

    def _cmd_preview(self, args, context) -> None:
        ref = self._current_ref(context)
        if ref:
            self._save_current(context)
            self.open_note(ref.path, mode="preview")

    def _cmd_split(self, args, context) -> None:
        ref = self._current_ref(context)
        if ref:
            self._save_current(context)
            self.open_note(ref.path, mode="split")

    def _cmd_backlinks(self, args, context) -> None:
        ref = self._resolve(" ".join(args)) if args else self._current_ref(context)
        if ref:
            self.show_backlinks(ref)

    def _cmd_graph(self, args, context) -> None:
        self.show_graph(self._current_ref(context))

    def _cmd_rename(self, args, context) -> None:
        ref = self._current_ref(context)
        if ref is None:
            self.notify("open a note first")
            return
        if args:
            self._rename_note(ref, " ".join(args))
        else:
            self.rename_note(ref)

    def _cmd_export(self, args, context) -> None:
        ref = self._current_ref(context)
        if ref is None:
            self.notify("open a note first")
            return
        fmt = args[0] if args else "html"
        out = Path(args[1]).expanduser() if len(args) > 1 else None
        self.export_note(ref, fmt=fmt, out=out)

    def _cmd_git(self, args, context) -> None:
        self.git_command(args[0] if args else "status", " ".join(args[1:]))

    def _cmd_set(self, args, context) -> None:
        if len(args) < 2:
            self.notify("usage: :set <key> <value>")
            return
        key, value = args[0], " ".join(args[1:])
        try:
            self.config.set(key, value)
        except (AttributeError, ValueError, TypeError) as error:
            self.notify(f"cannot set {key}: {error}", severity="error")
            return
        self.notify(f"{key} = {getattr(self.config, key.split('.')[0], value)}")
        if key.startswith("editor."):
            screen = self.screen
            if isinstance(screen, (EditorScreen, SplitScreen)):
                area = screen.query_one("#editor", MarkdownArea)
                area.show_line_numbers = self.config.editor.line_numbers
                area.soft_wrap = self.config.editor.soft_wrap
        if key == "list.sort":
            self.set_sort(str(value))
        if key == "theme":
            self._apply_theme(str(value))

    def _cmd_numbers(self, args, context) -> None:
        self.config.editor.line_numbers = not self.config.editor.line_numbers
        screen = self.screen
        if isinstance(screen, (EditorScreen, SplitScreen)):
            area = screen.query_one("#editor", MarkdownArea)
            area.show_line_numbers = self.config.editor.line_numbers
        self.notify(f"line numbers {'on' if self.config.editor.line_numbers else 'off'}")

    def _cmd_vim(self, args, context) -> None:
        screen = self.screen
        if not isinstance(screen, EditorScreen):
            self.notify("open a note to toggle vim mode")
            return
        keymap = "normal" if self.config.editor.keymap == "vim" else "vim"
        self.config.editor.keymap = keymap
        screen._setup_keymap(keymap)
        screen.update_status()
        self.notify(f"keymap: {keymap}")

    def _cmd_wrap(self, args, context) -> None:
        screen = self.screen
        if isinstance(screen, (EditorScreen, SplitScreen)):
            area = screen.query_one("#editor", MarkdownArea)
            area.soft_wrap = not area.soft_wrap
            self.config.editor.soft_wrap = area.soft_wrap
            self.notify(f"soft wrap {'on' if area.soft_wrap else 'off'}")

    def _cmd_share(self, args, context) -> None:
        ref = self._current_ref(context)
        if ref is None:
            self.notify("open a note first")
            return
        text = self.store.read_content(ref.path)
        if termux.share_send(f"{ref.title}\n\n{text}"):
            self.notify("shared")
        else:
            self.notify("share needs Termux:API (pkg install termux-api)", severity="warning")

    def _cmd_voice(self, args, context) -> None:
        self.voice_capture(" ".join(args))

    def _cmd_reindex(self, args, context) -> None:
        self.reindex()

    def _cmd_trash(self, args, context) -> None:
        self.show_trash()

    def _cmd_purge(self, args, context) -> None:
        days = int(args[0]) if args and args[0].isdigit() else None
        purged = self.store.purge_trash(days)
        self.notify(f"purged {purged} note(s)")

    def _cmd_reload(self, args, context) -> None:
        screen = self.screen
        if isinstance(screen, EditorScreen):
            screen.reload_from_disk()
            self.notify("reloaded from disk")

    def _cmd_help(self, args, context) -> None:
        self.show_help()

    _cmd_keys = _cmd_help

    def _cmd_version(self, args, context) -> None:
        info = self.store.stats()
        self.notify(
            f"tuinotes {__version__} · {info['notes']} notes · {info['words']} words · "
            f"index {'FTS5' if info['fts'] else 'LIKE'}"
        )

    # ------------------------------------------------------------------ extras
    def export_note(self, ref: NoteRef, fmt: str = "html", out: Optional[Path] = None) -> Optional[Path]:
        try:
            note = self.store.get(ref.path)
            target = out or exporter.default_export_path(ref, fmt)
            written = exporter.export_note(note, target, fmt=fmt, backend=self.config.export.pdf_backend)
        except (StorageError, exporter.ExportError) as error:
            self.notify(f"export failed: {error}", severity="error", timeout=8)
            return None
        self.notify(f"exported to {written}")
        return written

    def git_command(self, sub: str, argument: str = "") -> None:
        sub = (sub or "status").lower()
        try:
            if sub == "init":
                self.notify(self.git.init())
            elif sub == "status":
                self.notify(f"git: {self.git.status().describe()}")
            elif sub == "commit":
                message = argument or f"tuinotes: update {time.strftime('%Y-%m-%d %H:%M')}"
                created = self.git.commit(message)
                self.notify("git: committed" if created else "git: nothing to commit")
            elif sub == "push":
                self.notify(f"git: {self.git.push()}")
            elif sub == "pull":
                self.notify(f"git: {self.git.pull()}")
            elif sub == "log":
                rows = [(line.split(" ", 1)[0], line.split(" ", 1)[-1]) for line in self.git.log(20)]
                self.push_screen(MessageScreen("Git log", "", rows=rows or [("no commits", "")]))
            else:
                self.notify(f"unknown git command: {sub}")
        except GitError as error:
            self.notify(f"git {sub} failed: {error}", severity="error", timeout=8)

    def auto_commit(self, ref: NoteRef) -> None:
        """Auto-commit hook, called after every save."""
        if not (self.config.git.enabled and self.config.git.auto_commit):
            return
        self._auto_commit_worker(ref.title)

    @work(thread=True, exclusive=True)
    def _auto_commit_worker(self, title: str) -> None:
        try:
            message = self.git.auto_commit(title)
        except GitError:
            return
        if message:
            self.call_from_thread(self.notify, f"git: {message}")

    def reindex(self) -> None:
        self._reindex_worker()

    @work(thread=True, exclusive=True)
    def _reindex_worker(self) -> None:
        count = self.store.reindex()
        self.call_from_thread(self._refresh_list)
        self.call_from_thread(self.notify, f"indexed {count} notes")

    def voice_capture(self, seed: str = "") -> None:
        """Dictate a note via Termux:API (bonus challenge)."""
        self._voice_worker(seed)

    @work(thread=True, exclusive=True)
    def _voice_worker(self, seed: str) -> None:
        try:
            spoken = termux.listen()
        except termux.TermuxUnavailable as error:
            self.call_from_thread(self.notify, str(error), severity="warning")
            return
        text = " ".join(part for part in (seed, spoken) if part).strip()
        if not text:
            self.call_from_thread(self.notify, "nothing captured")
            return
        note = self.store.create(content=text)
        self.call_from_thread(self.notify, f"voice note: {note.ref.title}")
        self.call_from_thread(self.open_note, note.path, "edit")

    def template_names(self) -> List[str]:
        from tuinotes.templates import available_templates

        return available_templates(self.config)

    def set_sort(self, key: str) -> None:
        from tuinotes.models import SORT_LABELS

        if key not in SORT_LABELS:
            self.notify(f"unknown sort: {key} (try {', '.join(SORT_LABELS)})", severity="error")
            return
        self.config.list.sort = key
        if isinstance(self.screen, NoteListScreen):
            self.screen.sort = key
            self.screen.load_notes(reset=True)
        elif self.list_screen is not None:
            self.list_screen.sort = key
            self.list_screen.load_notes(reset=True)
        self.notify(f"sort: {key}")

    def save_config(self) -> None:
        try:
            self.config.save()
        except OSError as error:  # pragma: no cover - read-only filesystem
            self.notify(f"could not save config: {error}", severity="warning")

    # ------------------------------------------------------- palette callbacks
    def palette_new_note(self) -> None:
        self.new_note()

    def palette_daily_note(self) -> None:
        self._cmd_daily((), None)

    def palette_preview(self) -> None:
        self._cmd_preview((), None)

    def palette_split(self) -> None:
        self._cmd_split((), None)

    def palette_graph(self) -> None:
        self.show_graph()

    def palette_tags(self) -> None:
        self.show_tags()

    def palette_trash(self) -> None:
        self.show_trash()

    def palette_reindex(self) -> None:
        self.reindex()

    def palette_help(self) -> None:
        self.show_help()

    def palette_save(self) -> None:
        self._cmd_w((), None)

    # ---------------------------------------------------------------- bindings
    def action_app_new_note(self) -> None:
        if isinstance(self.screen, (EditorScreen, SplitScreen)):
            self._save_current()
        self.new_note()

    def action_app_help(self) -> None:
        self.show_help()

    def action_quit_app(self) -> None:
        """Save, persist config and exit (``App.action_quit`` is async upstream)."""
        self._save_current()
        self.save_config()
        if self.config.termux.keep_awake and termux.is_termux():
            termux.wake_lock(False)
        self.exit()


def run_app(
    store: NoteStore,
    config: Config,
    *,
    initial_note: Optional[str] = None,
    initial_mode: str = "edit",
) -> int:
    """Create and run the app; returns the process exit code."""
    app = TuinotesApp(store, config, initial_note=initial_note, initial_mode=initial_mode)
    app.run()
    return 0


def build_app(
    store: NoteStore, config: Config, *, initial_note: Optional[str] = None
) -> TuinotesApp:
    """Build (but do not run) the app — handy for tests and screenshots."""
    return TuinotesApp(store, config, initial_note=initial_note)


__all__ = ["TuinotesApp", "run_app", "build_app", "Theme"]
