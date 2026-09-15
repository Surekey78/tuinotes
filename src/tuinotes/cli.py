"""Command line interface.

Two entry points are installed:

``tuinotes``
    Full app: ``tuinotes`` opens the TUI, ``tuinotes list|search|export|git …``
    do one thing and exit.
``note``
    Fast capture: ``note "buy milk"`` writes a note and exits in well under a
    second, because Textual is never imported on that path.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Sequence

from rich.console import Console
from rich.table import Table
from rich.text import Text

from tuinotes import __version__, exporter, termux
from tuinotes.config import Config, load_config, write_default_config
from tuinotes.models import SORT_LABELS, Note, NoteRef
from tuinotes.storage import NoteNotFound, NoteStore, StorageError

console = Console()
error_console = Console(stderr=True, style="bold red")

SORT_CHOICES = tuple(SORT_LABELS)


# --------------------------------------------------------------------- plumbing
def _store(args: argparse.Namespace) -> tuple[NoteStore, Config]:
    config = load_config(notes_dir=getattr(args, "vault", None))
    store = NoteStore(config)
    store.sync()
    return store, config


def _resolve(store: NoteStore, needle: str) -> NoteRef:
    try:
        return store.resolve(needle)
    except NoteNotFound as error:
        error_console.print(str(error))
        raise SystemExit(2) from error


def _fail(message: str, code: int = 1) -> int:
    error_console.print(message)
    return code


def _json(data) -> None:
    console.print_json(json.dumps(data, default=str, indent=2))


def _emit(data, rows, *, as_json: bool, title: str = "") -> None:
    """Print either JSON or a rich table."""
    if as_json:
        _json(data)
        return
    if not rows:
        console.print("[dim]nothing to show[/dim]")
        return
    table = Table(title=title or None, show_lines=False, pad_edge=False)
    for column in rows[0]:
        table.add_column(column, overflow="fold")
    for row in rows:
        table.add_row(*[str(cell) for cell in row.values()])
    console.print(table)


# ------------------------------------------------------------------ subcommand: TUI
def cmd_tui(args: argparse.Namespace) -> int:
    store, config = _store(args)
    from tuinotes.tui.app import run_app  # imported late: keeps the CLI snappy

    if args.note:
        try:
            initial = store.resolve(args.note).path
        except NoteNotFound as error:
            return _fail(str(error))
    else:
        initial = None
    if config.daily.enabled and initial is None and args.daily:
        note = store.daily_note()
        initial = note.path
    try:
        return run_app(store, config, initial_note=initial, initial_mode=args.mode)
    except KeyboardInterrupt:  # pragma: no cover - interactive
        return 130


# --------------------------------------------------------------------- creation
def cmd_new(args: argparse.Namespace) -> int:
    store, config = _store(args)
    content = ""
    if args.content == "-":
        content = sys.stdin.read()
    elif args.content:
        content = args.content
    try:
        note = store.create(
            title=args.title,
            content=content,
            tags=args.tag or [],
            template=args.template,
            folder=args.folder or "",
        )
    except (StorageError, KeyError) as error:
        return _fail(str(error))
    _announce(store, config, note, args)
    return 0


def cmd_quick(args: argparse.Namespace) -> int:
    """``note "thought"`` — capture and get out of the way."""
    store, config = _store(args)
    text = " ".join(args.text).strip()
    if not text and not sys.stdin.isatty():
        text = sys.stdin.read().strip()
    if not text:
        if termux.is_termux() and termux.has_command("termux-dialog"):
            result = subprocess.run(
                ["termux-dialog", "text", "-t", "Quick note"],
                capture_output=True,
                text=True,
                check=False,
            )
            text = (result.stdout or "").strip()
        if not text:
            return _fail("nothing to capture (usage: note \"your thought\")")
    tags = args.tag or []
    note = store.create(content=text, tags=tags, folder=args.folder or "")
    _announce(store, config, note, args)
    return 0


def _announce(store: NoteStore, config: Config, note: Note, args: argparse.Namespace) -> None:
    path = store.root / note.ref.path
    if getattr(args, "json", False):
        _json(note.ref.to_dict() | {"file": str(path)})
        return
    console.print(
        Text.assemble(
            ("✓ ", "green"),
            (note.ref.title, "bold"),
            ("  ", ""),
            (f"{note.ref.word_count} words", "dim"),
            ("  ", ""),
            (str(path), "dim cyan"),
        )
    )
    if config.termux.notifications and termux.is_termux():
        termux.notify("tuinotes", f"saved: {note.ref.title}")
    if getattr(args, "open", False):
        from tuinotes.tui.app import run_app

        run_app(store, config, initial_note=note.ref.path)
    if getattr(args, "edit", False):
        _external_editor(store, config, note.ref)


def cmd_daily(args: argparse.Namespace) -> int:
    store, config = _store(args)
    note = store.daily_note(template=args.template)
    if args.open:
        from tuinotes.tui.app import run_app

        return run_app(store, config, initial_note=note.ref.path)
    if getattr(args, "json", False):
        _json(note.ref.to_dict())
    else:
        console.print(f"{note.ref.title} → {store.root / note.ref.path}")
    return 0


# ----------------------------------------------------------------------- listing
def cmd_list(args: argparse.Namespace) -> int:
    store, _ = _store(args)
    refs = store.list_notes(sort=args.sort, tags=args.tag or [], limit=args.limit)
    if args.json:
        _json([ref.to_dict() for ref in refs])
        return 0
    if not refs:
        console.print("[dim]no notes yet — create one with:[/dim] note \"hello world\"")
        return 0
    table = Table(show_header=True, header_style="bold", pad_edge=False, show_lines=False)
    table.add_column("Note", overflow="fold", ratio=2)
    table.add_column("Preview", overflow="fold", ratio=3)
    table.add_column("Tags", overflow="fold", style="cyan")
    table.add_column("When", justify="right", style="dim")
    for ref in refs:
        marker = "🔒 " if ref.encrypted else ("↗ " if ref.links else "")
        table.add_row(marker + ref.title, ref.preview, ref.tag_str, ref.relative_time())
    console.print(table)
    console.print(f"[dim]{len(refs)} of {store.count()} notes · sort: {args.sort}[/dim]")
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    store, config = _store(args)
    results = store.search(args.query, tags=args.tag or [], limit=args.limit)
    if args.json:
        _json(
            [
                {
                    "path": result.path,
                    "title": result.ref.title,
                    "score": round(result.score, 3),
                    "snippet": result.snippet,
                }
                for result in results
            ]
        )
        return 0
    if not results:
        console.print(f"[dim]no matches for “{args.query}”[/dim]")
        return 0
    from tuinotes.search import highlight

    needles = [token for token in args.query.split() if not token.startswith("#")]
    for result in results:
        console.print(
            Text.assemble(
                (f"{result.score:0.2f} ", "dim"),
                highlight(result.ref.title, needles),
                ("  ", ""),
                (result.ref.relative_time(), "dim"),
                ("  " + result.ref.tag_str if result.ref.tag_str else "", "cyan"),
            )
        )
        if result.snippet and args.snippets:
            console.print(Text.assemble(("    ", ""), (result.snippet, "dim")))
    console.print(f"[dim]{len(results)} match(es)[/dim]")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    store, _ = _store(args)
    ref = _resolve(store, args.note)
    content = store.read_content(ref.path)
    if args.raw:
        console.print(content, markup=False, highlight=False)
        return 0
    if args.json:
        _json({**ref.to_dict(), "content": content})
        return 0
    from rich.markdown import Markdown

    console.print(Markdown(content))
    return 0


def _external_editor(store: NoteStore, config: Config, ref: NoteRef) -> None:
    editor = os.environ.get("VISUAL") or os.environ.get("EDITOR") or "vi"
    target = store.root / ref.path
    before = target.read_text(encoding="utf-8", errors="replace")
    subprocess.run([editor, str(target)], check=False)
    after = target.read_text(encoding="utf-8", errors="replace")
    if after != before:
        store.index_path(ref.path)
        console.print(f"[green]saved[/green] {target}")


def cmd_edit(args: argparse.Namespace) -> int:
    store, config = _store(args)
    ref = _resolve(store, args.note)
    if args.tui:
        from tuinotes.tui.app import run_app

        return run_app(store, config, initial_note=ref.path)
    _external_editor(store, config, ref)
    return 0


def cmd_tags(args: argparse.Namespace) -> int:
    store, _ = _store(args)
    counts = store.tag_counts()
    if args.json:
        _json([{"tag": tag, "count": count} for tag, count in counts])
        return 0
    if not counts:
        console.print("[dim]no tags yet — write #hashtags inside your notes[/dim]")
        return 0
    table = Table(show_header=True, header_style="bold", pad_edge=False)
    table.add_column("Tag", style="cyan")
    table.add_column("Notes", justify="right")
    table.add_column("Bar")
    top = max(count for _, count in counts)
    for tag, count in counts:
        bar = "█" * max(1, round(count / top * 24))
        table.add_row(f"#{tag}", str(count), Text(bar, style="green"))
    console.print(table)
    return 0


def cmd_backlinks(args: argparse.Namespace) -> int:
    store, _ = _store(args)
    ref = _resolve(store, args.note)
    incoming = store.backlinks(ref)
    outgoing = store.outgoing(ref)
    if args.json:
        _json(
            {
                "note": ref.to_dict(),
                "backlinks": [item.to_dict() for item in incoming],
                "links": [{"target": link, "resolved": bool(target)} for link, target in outgoing],
            }
        )
        return 0
    console.print(Text.assemble(("Links to ", "bold"), (ref.title, "cyan")))
    if incoming:
        for item in incoming:
            console.print(f"  ← {item.title} [dim]({item.path})[/dim]")
    else:
        console.print("  [dim]no notes link here yet[/dim]")
    console.print(Text.assemble(("Links from ", "bold"), (ref.title, "cyan")))
    if outgoing:
        for _link, target in outgoing:
            state = f"→ {target.title}" if target else "[dim]missing note[/dim]"
            console.print(f"  {state}")
    else:
        console.print("  [dim]no outgoing links[/dim]")
    return 0


def cmd_graph(args: argparse.Namespace) -> int:
    store, config = _store(args)
    from tuinotes.graph import LinkGraph

    graph = LinkGraph.build(store.all_refs())
    if args.note:
        ref = _resolve(store, args.note)
        graph = graph.subgraph(ref.path, depth=args.depth)
    if args.json:
        _json(
            {
                "stats": graph.stats(),
                "edges": [{"from": a, "to": b} for a, b in graph.edge_list()],
            }
        )
        return 0
    console.print(graph.render_text(width=min(args.width or 90, console.width or 90)))
    stats = graph.stats()
    console.print(
        f"[dim]{stats['notes']} notes · {stats['links']} links · "
        f"{stats['clusters']} clusters · {stats['orphans']} unlinked[/dim]"
    )
    return 0


# ----------------------------------------------------------------------- mutators
def cmd_delete(args: argparse.Namespace) -> int:
    store, config = _store(args)
    ref = _resolve(store, args.note)
    if config.confirm_delete and not args.yes:
        answer = console.input(f"Delete [bold]{ref.title}[/bold]? [y/N] ")
        if answer.strip().lower() not in {"y", "yes"}:
            console.print("[dim]cancelled[/dim]")
            return 1
    trash_name = store.delete(ref, permanent=args.permanent)
    if args.permanent:
        console.print(f"[red]deleted[/red] {ref.title} permanently")
    else:
        console.print(
            f"[yellow]trashed[/yellow] {ref.title} "
            f"(restore within {config.trash.retention_days} days: tuinotes restore {trash_name})"
        )
    return 0


def cmd_restore(args: argparse.Namespace) -> int:
    store, _ = _store(args)
    entries = store.list_trash()
    if not entries:
        console.print("[dim]trash is empty[/dim]")
        return 0
    if not args.note:
        for entry in entries:
            console.print(
                f"{entry.path}  [bold]{entry.title}[/bold]  "
                f"[dim]{entry.original_path} · {entry.relative_time()} ago · "
                f"{entry.age_days:.0f}d old[/dim]"
            )
        return 0
    ref = store.restore(args.note)
    console.print(f"[green]restored[/green] {ref.title} → {ref.path}")
    return 0


def cmd_purge(args: argparse.Namespace) -> int:
    store, config = _store(args)
    days = args.days if args.days is not None else config.trash.retention_days
    purged = store.purge_trash(days)
    console.print(f"purged {purged} note(s) older than {days} days")
    return 0


def cmd_rename(args: argparse.Namespace) -> int:
    store, _ = _store(args)
    ref = _resolve(store, args.note)
    note = store.rename(ref, args.title)
    console.print(f"[green]renamed[/green] → {note.ref.path}")
    return 0


def cmd_tag(args: argparse.Namespace) -> int:
    store, _ = _store(args)
    ref = _resolve(store, args.note)
    if args.remove:
        note = store.remove_tags(ref, args.tags)
    else:
        note = store.add_tags(ref, args.tags)
    console.print(f"{note.ref.title}: {note.ref.tag_str or '(no tags)'}")
    return 0


# ------------------------------------------------------------------------ export
def cmd_export(args: argparse.Namespace) -> int:
    store, config = _store(args)
    fmt = args.format
    if args.all:
        refs = store.list_notes(limit=0)
        target_dir = Path(args.out).expanduser() if args.out else Path.cwd() / "tuinotes-export"
        written: List[Path] = []
        for ref in refs:
            note = store.get(ref.path)
            written.append(
                exporter.export_note(
                    note,
                    target_dir / f"{ref.stem}.{fmt}",
                    fmt=fmt,
                    backend=config.export.pdf_backend,
                )
            )
        console.print(f"exported {len(written)} note(s) to {target_dir}")
        return 0
    ref = _resolve(store, args.note or "")
    note = store.get(ref.path)
    target = (
        Path(args.out).expanduser()
        if args.out
        else exporter.default_export_path(ref, fmt, Path(args.out_dir).expanduser() if args.out_dir else None)
    )
    try:
        exported = exporter.export_note(
            note, target, fmt=fmt, backend=args.backend or config.export.pdf_backend
        )
    except exporter.ExportError as error:
        return _fail(str(error))
    console.print(f"exported {ref.title} → {exported}")
    return 0


# -------------------------------------------------------------------- encryption
def cmd_encrypt(args: argparse.Namespace) -> int:
    store, config = _store(args)
    ref = _resolve(store, args.note)
    if ref.encrypted:
        console.print(f"{ref.title} is already encrypted")
        return 0
    if not exporter_available(config):
        return _fail("gpg is required (on Termux: pkg install gnupg)")
    from tuinotes import encryption

    target = store.root / ref.path
    try:
        encrypted = encryption.encrypt_file(target, config.encryption)
    except encryption.EncryptionError as error:
        return _fail(str(error))
    store.reindex()
    console.print(f"[green]encrypted[/green] {encrypted.name}")
    return 0


def cmd_decrypt(args: argparse.Namespace) -> int:
    store, config = _store(args)
    ref = _resolve(store, args.note)
    if not ref.encrypted:
        console.print(f"{ref.title} is not encrypted")
        return 0
    from tuinotes import encryption

    try:
        plain = encryption.decrypt_file(store.root / ref.path, config.encryption)
    except encryption.EncryptionError as error:
        return _fail(str(error))
    store.reindex()
    console.print(f"[green]decrypted[/green] {plain.name}")
    return 0


def exporter_available(config: Config) -> bool:
    from tuinotes import encryption

    return encryption.available(config.encryption.gpg_binary)


# ----------------------------------------------------------------------- termux
def cmd_share(args: argparse.Namespace) -> int:
    store, config = _store(args)
    if args.send:
        ref = _resolve(store, args.send)
        text = store.read_content(ref.path)
        if termux.share_send(f"{ref.title}\n\n{text}"):
            console.print("shared")
            return 0
        return _fail("share failed — is Termux:API installed? (pkg install termux-api)")
    try:
        text = termux.share_receive()
    except termux.TermuxUnavailable as error:
        return _fail(str(error))
    if not text.strip():
        console.print("[dim]nothing shared[/dim]")
        return 0
    note = store.create(content=text)
    console.print(f"[green]captured[/green] {note.ref.title} → {store.root / note.ref.path}")
    return 0


def cmd_notify(args: argparse.Namespace) -> int:
    if termux.notify(args.title, args.message or ""):
        return 0
    return _fail("notification failed — is Termux:API installed? (pkg install termux-api)")


def cmd_voice(args: argparse.Namespace) -> int:
    store, config = _store(args)
    try:
        spoken = termux.listen()
    except termux.TermuxUnavailable as error:
        return _fail(str(error))
    if not spoken.strip():
        console.print("[dim]nothing captured[/dim]")
        return 0
    note = store.create(content=spoken)
    console.print(f"[green]voice note[/green] {note.ref.title} → {store.root / note.ref.path}")
    return 0


def cmd_clipboard(args: argparse.Namespace) -> int:
    store, config = _store(args)
    if args.note:
        ref = _resolve(store, args.note)
        text = store.read_content(ref.path)
        if termux.clipboard_copy(text):
            console.print(f"copied {ref.title}")
            return 0
        return _fail("clipboard failed — is Termux:API installed?")
    text = termux.clipboard_paste()
    if not text.strip():
        console.print("[dim]clipboard is empty[/dim]")
        return 0
    note = store.create(content=text)
    console.print(f"[green]captured[/green] {note.ref.title}")
    return 0


def cmd_widget(args: argparse.Namespace) -> int:
    if args.action == "install":
        for path in termux.install_widgets():
            console.print(f"[green]installed[/green] {path}")
        console.print("[dim]open the Termux:Widget app to see the shortcuts[/dim]")
        return 0
    if args.action == "uninstall":
        for path in termux.uninstall_widgets():
            console.print(f"[yellow]removed[/yellow] {path}")
        return 0
    installed = termux.list_widgets()
    if not installed:
        console.print("[dim]no widgets installed — run: tuinotes widget install[/dim]")
        return 0
    for path in installed:
        console.print(str(path))
    return 0


def cmd_setup(args: argparse.Namespace) -> int:
    if args.what == "termux":
        path = termux.configure_properties()
        console.print(f"wrote {path}")
        termux.reload_settings()
        console.print("[dim]restart Termux for the new extra-keys row to appear[/dim]")
        return 0
    if args.what == "dirs":
        store, _ = _store(args)
        store.ensure_dirs()
        console.print(f"vault ready at {store.root}")
        return 0
    return _fail(f"unknown setup target: {args.what}")


# -------------------------------------------------------------------------- git
def cmd_git(args: argparse.Namespace) -> int:
    from tuinotes.git_sync import GitError, from_config

    store, config = _store(args)
    git = from_config(config)
    try:
        if args.action == "init":
            console.print(git.init())
        elif args.action == "status":
            status = git.status()
            console.print(f"[bold]{status.describe()}[/bold]")
            for change in status.changed[:20]:
                console.print(f"  [dim]{change}[/dim]")
        elif args.action == "commit":
            created = git.commit(args.message or f"tuinotes: {datetime.now():%Y-%m-%d %H:%M}")
            console.print("committed" if created else "nothing to commit")
        elif args.action == "push":
            console.print(git.push())
        elif args.action == "pull":
            console.print(git.pull())
        elif args.action == "log":
            for line in git.log(args.limit):
                console.print(line)
        else:
            return _fail(f"unknown git action: {args.action}")
    except GitError as error:
        return _fail(str(error))
    return 0


# ------------------------------------------------------------------------ config
def cmd_config(args: argparse.Namespace) -> int:
    config = load_config(notes_dir=args.vault)
    if args.action == "path":
        console.print(str(config.config_file))
        return 0
    if args.action == "init":
        target = config.config_file
        written = write_default_config(target, notes_dir=args.vault)
        console.print(f"wrote {written}")
        return 0
    if args.action == "set":
        if not args.pair or "=" not in args.pair:
            return _fail("usage: tuinotes config set key=value")
        key, value = args.pair.split("=", 1)
        try:
            config.set(key.strip(), value.strip())
        except (AttributeError, ValueError, TypeError) as error:
            return _fail(f"cannot set {key}: {error}")
        target = config.save()
        console.print(f"{key} = {config.get(key.strip())}  [dim]({target})[/dim]")
        return 0
    if args.json:
        _json(config.to_dict())
        return 0
    console.print(f"[bold]config[/bold] [dim]source: {config.source}[/dim]")
    console.print(f"  vault      {config.root}")
    console.print(f"  index      {config.metadata_db}")
    console.print(f"  trash      {config.trash_dir} ({config.trash.retention_days} days)")
    console.print(f"  templates  {config.templates_dir_path}")
    console.print(f"  theme      {config.theme}")
    console.print(f"  sort       {config.list.sort}")
    console.print(f"  keymap     {config.editor.keymap}")
    console.print(f"  autosave   {'on' if config.editor.autosave else 'off'} "
                  f"({config.editor.autosave_interval}s)")
    console.print(f"  git        {'on' if config.git.enabled else 'off'}")
    console.print(f"  termux     {termux.detect().describe()}")
    return 0


def cmd_templates(args: argparse.Namespace) -> int:
    from tuinotes.templates import available_templates, describe, import_templates, load_template

    _, config = _store(args)
    if args.action == "install":
        written = import_templates(config, overwrite=args.force)
        console.print(f"installed {len(written)} template(s) into {config.templates_dir_path}")
        return 0
    if args.action == "show":
        if not args.name:
            return _fail("usage: tuinotes templates show <name>")
        console.print(load_template(args.name, config), markup=False)
        return 0
    table = Table(show_header=True, header_style="bold", pad_edge=False)
    table.add_column("Template")
    table.add_column("Description")
    for name in available_templates(config):
        table.add_row(name, describe(name, config))
    console.print(table)
    return 0


# ------------------------------------------------------------------- maintenance
def cmd_stats(args: argparse.Namespace) -> int:
    store, config = _store(args)
    info = store.stats()
    if args.json:
        _json(info)
        return 0
    console.print(f"[bold]vault[/bold]     {info['vault']}")
    console.print(f"notes       {info['notes']}")
    console.print(f"words       {info['words']}")
    console.print(f"size        {int(info['bytes']) / 1024:.1f} KB")
    console.print(f"tags        {info['tags']}")
    console.print(f"linked      {info['linked']} notes use wikilinks")
    console.print(f"encrypted   {info['encrypted']}")
    console.print(f"trash       {info['trash']} note(s)")
    console.print(f"index       {int(info['index_bytes']) / 1024:.1f} KB "
                  f"({'FTS5' if info['fts'] else 'LIKE fallback'})")
    return 0


def cmd_reindex(args: argparse.Namespace) -> int:
    store, _ = _store(args)
    count = store.reindex()
    console.print(f"indexed {count} note(s)")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    store, config = _store(args)
    from tuinotes import encryption
    from tuinotes.git_sync import GitSync

    checks = []
    checks.append(("python", sys.version.split()[0], True))
    try:
        import textual

        textual_version = getattr(textual, "__version__", "unknown")
    except ImportError:  # pragma: no cover
        textual_version = "missing"
    checks.append(("textual", textual_version, textual_version != "missing"))
    checks.append(("vault", str(config.root), config.root.is_dir()))
    checks.append(("writable", str(config.root), os.access(config.root, os.W_OK)))
    checks.append(("index", str(config.metadata_db), config.metadata_db.is_file()))
    checks.append(("full-text search", "FTS5" if store._has_fts else "LIKE fallback", True))
    checks.append(("git", "installed" if GitSync.available() else "missing", GitSync.available()))
    checks.append(("gpg", "installed" if encryption.available() else "missing", encryption.available()))
    checks.append(("pandoc (pdf)", "installed" if exporter.pdf_backend("auto") else "missing", True))
    checks.append(("termux", termux.detect().describe(), True))
    try:
        from tuinotes.tui.markdown_area import NATIVE_HIGHLIGHTING

        checks.append(
            (
                "editor highlighting",
                "tree-sitter" if NATIVE_HIGHLIGHTING else "built-in regex (add the syntax extra for tree-sitter)",
                True,
            )
        )
    except ImportError:  # pragma: no cover
        checks.append(("editor highlighting", "unavailable", False))
    checks.append(("shortcuts", f"{len(termux.list_widgets())} installed", True))

    failed = 0
    for name, detail, ok in checks:
        mark = "[green]ok[/green]  " if ok else "[red]warn[/red]"
        console.print(f"{mark} {name:<20} {detail}")
        failed += 0 if ok else 1
    if termux.is_termux() and termux.properties_needs_update():
        console.print("[dim]tip: tuinotes setup termux  →  adds a note-taking extra-keys row[/dim]")
    return 1 if failed and args.strict else 0


def cmd_version(args: argparse.Namespace) -> int:
    console.print(f"tuinotes {__version__}")
    return 0


# ----------------------------------------------------------------------- parser
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tuinotes",
        description="Fast Markdown notes for Termux and every other terminal.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  tuinotes                       open the TUI\n"
            "  note \"read the rust book\"       capture a note instantly\n"
            "  tuinotes search rust --tag docs\n"
            "  tuinotes daily --open\n"
            "  tuinotes export note --format html\n"
        ),
    )
    parser.add_argument("--vault", help="notes directory (default: ~/notes or $TUINOTES_HOME)")
    parser.add_argument("--version", action="version", version=f"tuinotes {__version__}")
    sub = parser.add_subparsers(dest="command")

    def add(name: str, help_text: str, func, **kwargs) -> argparse.ArgumentParser:
        child = sub.add_parser(name, help=help_text, **kwargs)
        child.set_defaults(func=func)
        child.add_argument("--vault", help="notes directory", default=None)
        return child

    # tui
    tui = add("tui", "open the terminal interface", cmd_tui)
    tui.add_argument("note", nargs="?", help="note to open")
    tui.add_argument("--mode", choices=("edit", "preview", "split"), default="edit")
    tui.add_argument("--daily", action="store_true", help="open today's note")

    new = add("new", "create a note", cmd_new)
    new.add_argument("title", nargs="?", help="note title")
    new.add_argument("-t", "--tag", action="append", help="tag (repeatable)")
    new.add_argument("--template", help="template name (see: tuinotes templates)")
    new.add_argument("--folder", help="sub-folder inside the vault")
    new.add_argument("-c", "--content", help="note body (use - to read stdin)")
    new.add_argument("--open", action="store_true", help="open it in the TUI")
    new.add_argument("--edit", action="store_true", help="open it in $EDITOR")
    new.add_argument("--json", action="store_true")

    quick = add("quick", "capture a note from the command line", cmd_quick)
    quick.add_argument("text", nargs="*", help="the note text")
    quick.add_argument("-t", "--tag", action="append")
    quick.add_argument("--folder")
    quick.add_argument("--open", action="store_true")
    quick.add_argument("--json", action="store_true")

    daily = add("daily", "open or create today's note", cmd_daily)
    daily.add_argument("--template")
    daily.add_argument("--open", action="store_true")
    daily.add_argument("--json", action="store_true")

    listing = add("list", "list notes", cmd_list, aliases=("ls",))
    listing.add_argument("--sort", choices=SORT_CHOICES, default=None)
    listing.add_argument("-t", "--tag", action="append")
    listing.add_argument("--limit", type=int, default=50)
    listing.add_argument("--json", action="store_true")

    search = add("search", "full-text + fuzzy search", cmd_search, aliases=("s",))
    search.add_argument("query")
    search.add_argument("-t", "--tag", action="append")
    search.add_argument("--limit", type=int, default=25)
    search.add_argument("--no-snippets", dest="snippets", action="store_false")
    search.add_argument("--json", action="store_true")

    show = add("show", "print a note", cmd_show, aliases=("cat",))
    show.add_argument("note")
    show.add_argument("--raw", action="store_true", help="print raw markdown")
    show.add_argument("--json", action="store_true")

    edit = add("edit", "edit a note in $EDITOR", cmd_edit)
    edit.add_argument("note")
    edit.add_argument("--tui", action="store_true", help="use the built-in editor")

    delete = add("delete", "move a note to the trash", cmd_delete, aliases=("rm",))
    delete.add_argument("note")
    delete.add_argument("-y", "--yes", action="store_true")
    delete.add_argument("--permanent", action="store_true")

    restore = add("restore", "restore a note from the trash", cmd_restore)
    restore.add_argument("note", nargs="?", help="trash entry (omit to list trash)")

    purge = add("purge", "empty expired trash", cmd_purge)
    purge.add_argument("--days", type=int)

    rename = add("rename", "rename a note", cmd_rename)
    rename.add_argument("note")
    rename.add_argument("title")

    tag = add("tag", "add or remove tags", cmd_tag)
    tag.add_argument("note")
    tag.add_argument("tags", nargs="+")
    tag.add_argument("-r", "--remove", action="store_true")

    tags = add("tags", "list tags with counts", cmd_tags)
    tags.add_argument("--json", action="store_true")

    backlinks = add("backlinks", "show links to and from a note", cmd_backlinks, aliases=("bl",))
    backlinks.add_argument("note")
    backlinks.add_argument("--json", action="store_true")

    graph = add("graph", "draw the note graph", cmd_graph)
    graph.add_argument("note", nargs="?")
    graph.add_argument("--depth", type=int, default=2)
    graph.add_argument("--width", type=int, default=90)
    graph.add_argument("--json", action="store_true")

    export = add("export", "export notes to html/md/txt/pdf", cmd_export)
    export.add_argument("note", nargs="?")
    export.add_argument("--format", choices=("html", "md", "txt", "pdf"), default="html")
    export.add_argument("--out", help="output file (or directory with --all)")
    export.add_argument("--out-dir", help="output directory for a single note")
    export.add_argument("--all", action="store_true", help="export the whole vault")
    export.add_argument("--backend", choices=("auto", "pandoc", "weasyprint"))

    encrypt = add("encrypt", "encrypt a note with gpg", cmd_encrypt)
    encrypt.add_argument("note")
    decrypt = add("decrypt", "decrypt a note", cmd_decrypt)
    decrypt.add_argument("note")

    share = add("share", "receive/send text via the Android share sheet", cmd_share)
    share.add_argument("--send", help="note to share out")

    notify = add("notify", "post an Android notification", cmd_notify)
    notify.add_argument("title")
    notify.add_argument("message", nargs="?")

    add("voice", "dictate a note (Termux:API)", cmd_voice)

    clipboard = add("clipboard", "capture the clipboard as a note", cmd_clipboard)
    clipboard.add_argument("--note", help="copy a note to the clipboard instead")

    widget = add("widget", "manage Termux:Widget shortcuts", cmd_widget)
    widget.add_argument("action", choices=("install", "uninstall", "list"), nargs="?", default="list")

    setup = add("setup", "configure Termux keys or the vault", cmd_setup)
    setup.add_argument("what", choices=("termux", "dirs"))

    git = add("git", "git sync for the vault", cmd_git)
    git.add_argument("action", choices=("init", "status", "commit", "push", "pull", "log"))
    git.add_argument("-m", "--message")
    git.add_argument("--limit", type=int, default=10)

    config = add("config", "show or change settings", cmd_config)
    config.add_argument("action", choices=("show", "set", "init", "path"), nargs="?", default="show")
    config.add_argument("pair", nargs="?", help="key=value for set")
    config.add_argument("--json", action="store_true")

    templates = add("templates", "list, show or install templates", cmd_templates)
    templates.add_argument("action", choices=("list", "show", "install"), nargs="?", default="list")
    templates.add_argument("name", nargs="?")
    templates.add_argument("--force", action="store_true")

    stats = add("stats", "vault statistics", cmd_stats)
    stats.add_argument("--json", action="store_true")

    add("reindex", "rebuild the note index", cmd_reindex)

    doctor = add("doctor", "check the environment", cmd_doctor)
    doctor.add_argument("--strict", action="store_true")

    add("version", "print the version", cmd_version)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """``tuinotes`` entry point."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        args.command = "tui"
        args.note = None
        args.mode = "edit"
        args.daily = True
        args.func = cmd_tui
    if args.command == "list" and args.sort is None:
        args.sort = load_config(notes_dir=args.vault).list.sort
    try:
        return int(args.func(args) or 0)
    except KeyboardInterrupt:  # pragma: no cover - interactive
        return 130
    except SystemExit as exit_signal:
        # Handlers may bail out early; turn that into a normal return value so
        # `main()` is always a pure "exit code" function.
        return int(exit_signal.code or 0)
    except StorageError as error:
        return _fail(str(error))


def quick_main(argv: Optional[Sequence[str]] = None) -> int:
    """``note`` entry point: minimal parsing, maximum speed."""
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(
        prog="note",
        description="Capture a note instantly: note \"your thought\"",
        add_help=False,
    )
    parser.add_argument("text", nargs="*")
    parser.add_argument("-t", "--tag", action="append")
    parser.add_argument("--folder")
    parser.add_argument("--open", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--vault")
    parser.add_argument("-l", "--list", action="store_true", help="list notes")
    parser.add_argument("-s", "--search")
    parser.add_argument("--daily", action="store_true", help="open today's note")
    parser.add_argument("--voice", action="store_true", help="dictate a note")
    parser.add_argument("--share", action="store_true", help="capture shared text")
    parser.add_argument("-h", "--help", action="store_true")
    args = parser.parse_args(argv)

    if args.help or (not args.text and not any([args.list, args.search, args.daily, args.voice, args.share])):
        console.print(
            "[bold]note[/bold] — instant capture for tuinotes\n\n"
            "  note \"buy milk\"          save a note\n"
            "  note -t idea \"app idea\"   save with a tag\n"
            "  note --daily              open today's note\n"
            "  note --list               list notes\n"
            "  note --search rust        search notes\n"
            "  note --voice              dictate a note (Termux)\n"
            "  tuinotes                  open the full app\n"
        )
        return 0
    if args.list:
        args.sort = load_config(notes_dir=args.vault).list.sort
        args.limit = 50
        args.json = args.json
        return cmd_list(args)
    if args.search:
        args.query = args.search
        args.limit = 25
        args.snippets = True
        return cmd_search(args)
    if args.daily:
        args.template = None
        args.open = args.open
        return cmd_daily(args)
    if args.voice:
        return cmd_voice(args)
    if args.share:
        args.send = None
        return cmd_share(args)
    return cmd_quick(args)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
