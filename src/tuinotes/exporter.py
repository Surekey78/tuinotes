"""Export notes to HTML (built in) and PDF (via ``pandoc``/``weasyprint``).

HTML export uses rich's renderer, so a note exported from your phone looks like
the preview you just read — no network, no external converter.
"""

from __future__ import annotations

import html
import io
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Iterable, List, Optional

from rich.console import Console
from rich.markdown import Markdown

from tuinotes.models import Note, NoteRef

HTML_FORMAT = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title><!--TITLE--></title>
<style>
  :root { color-scheme: dark; }
  body {
    margin: 0 auto; padding: 2rem 1.25rem 4rem; max-width: 46rem;
    background: <!--BG-->; color: <!--FG-->;
    font: 17px/1.65 -apple-system, "Segoe UI", Roboto, "Noto Sans", sans-serif;
  }
  article > pre { white-space: pre-wrap; word-break: break-word; font: inherit; margin: 0; }
  header.meta { border-bottom: 1px solid #444; margin-bottom: 1.5rem; padding-bottom: .75rem;
                font-size: .85rem; opacity: .8; }
  .tags span { background: #2d3142; border-radius: 999px; padding: .1rem .55rem;
               margin-right: .35rem; font-size: .8rem; }
  footer { margin-top: 3rem; font-size: .75rem; opacity: .55; }
  @media print { body { color: #000; background: #fff; } }
</style>
</head>
<body>
<header class="meta">
  <div><strong><!--TITLE--></strong></div>
  <div><!--META--></div>
  <div class="tags"><!--TAGS--></div>
</header>
<article><!--BODY--></article>
<footer>Exported from tuinotes on <!--STAMP--></footer>
</body>
</html>
"""

PDF_BACKENDS = ("auto", "pandoc", "weasyprint")


class ExportError(RuntimeError):
    """Raised when an export cannot be completed."""


def markdown_to_html(note: Note | NoteRef, content: str = "", *, width: int = 100) -> str:
    """Render a note to a standalone HTML document."""
    if isinstance(note, Note):
        content = content or note.content
        ref = note.ref
    else:
        ref = note
    if not content and isinstance(note, Note):
        content = note.content

    console = Console(
        record=True,
        width=width,
        force_terminal=False,
        color_system="truecolor",
        file=io.StringIO(),
    )
    console.print(Markdown(content or f"# {ref.title}"), justify="left")
    body = console.export_html(code_format="<pre>{code}</pre>", inline_styles=True, clear=True)

    tags = "".join(f"<span>#{html.escape(tag)}</span>" for tag in ref.tags)
    meta = " · ".join(
        part
        for part in (
            ref.date_str("%Y-%m-%d %H:%M"),
            f"{ref.word_count} words",
            f"{ref.char_count} chars",
        )
        if part
    )
    # Marker replacement (not str.format) keeps the CSS braces intact.
    document = (
        HTML_FORMAT.replace("<!--BG-->", "#1e1e2e")
        .replace("<!--FG-->", "#e6e6e6")
        .replace("<!--BODY-->", body)
    )
    document = document.replace("<!--TITLE-->", html.escape(ref.title))
    document = document.replace("<!--META-->", html.escape(meta))
    document = document.replace("<!--TAGS-->", tags)
    document = document.replace("<!--STAMP-->", datetime.now().strftime("%Y-%m-%d %H:%M"))
    return document


def markdown_to_text(note: Note, *, keep_markup: bool = True) -> str:
    if keep_markup:
        return note.content
    console = Console(record=True, width=100, force_terminal=False, file=io.StringIO())
    console.print(Markdown(note.content))
    return console.export_text(clear=True, styles=False)


def pdf_backend(backend: str = "auto") -> Optional[str]:
    """Pick an available PDF backend (``pandoc`` preferred)."""
    if backend == "pandoc" or backend == "auto":
        if shutil.which("pandoc"):
            return "pandoc"
        if backend == "pandoc":
            raise ExportError("pandoc is not installed (on Termux: pkg install pandoc)")
    if backend == "weasyprint" or backend == "auto":
        try:
            import weasyprint  # noqa: F401

            return "weasyprint"
        except ImportError:
            if backend == "weasyprint":
                raise ExportError("weasyprint is not installed (pip install weasyprint)") from None
    if backend == "auto":
        return None
    raise ExportError(f"unknown PDF backend: {backend}")


def note_to_pdf(note: Note, target: Path, backend: str = "auto") -> Path:
    """Convert a note to PDF via pandoc or weasyprint."""
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    chosen = pdf_backend(backend)
    if chosen == "pandoc":
        result = subprocess.run(
            [
                "pandoc",
                "-f",
                "markdown",
                "-t",
                "pdf",
                "--pdf-engine=xelatex",
                "-V",
                "geometry:margin=2cm",
                "-o",
                str(target),
            ],
            input=note.content,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise ExportError(result.stderr.strip() or "pandoc failed")
        return target
    if chosen == "weasyprint":
        from weasyprint import HTML  # type: ignore

        HTML(string=markdown_to_html(note)).write_pdf(str(target))
        return target
    raise ExportError(
        "no PDF backend available — install pandoc (pkg install pandoc) "
        "or weasyprint (pip install weasyprint), or export to HTML instead"
    )


def export_note(note: Note, target: Path, fmt: str = "html", backend: str = "auto") -> Path:
    """Write a note to ``target`` in ``fmt`` (``html``, ``md``, ``txt`` or ``pdf``)."""
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    fmt = fmt.lower().lstrip(".")
    if fmt in {"html", "htm"}:
        target.write_text(markdown_to_html(note), encoding="utf-8")
    elif fmt in {"md", "markdown"}:
        target.write_text(note.content, encoding="utf-8")
    elif fmt in {"txt", "text"}:
        target.write_text(markdown_to_text(note, keep_markup=False), encoding="utf-8")
    elif fmt == "pdf":
        return note_to_pdf(note, target, backend=backend)
    else:
        raise ExportError(f"unsupported export format: {fmt} (use html, md, txt or pdf)")
    return target


def default_export_path(note: NoteRef, fmt: str = "html", directory: Optional[Path] = None) -> Path:
    directory = directory or Path.home() / "Downloads" / "tuinotes"
    slug = note.stem or "note"
    return directory / f"{slug}.{fmt}"


def export_many(
    notes: Iterable[Note],
    directory: Path,
    fmt: str = "html",
    backend: str = "auto",
) -> List[Path]:
    """Bulk export (used by ``tuinotes export --all``)."""
    directory = Path(directory)
    written: List[Path] = []
    for note in notes:
        target = directory / f"{note.ref.stem}.{fmt}"
        written.append(export_note(note, target, fmt=fmt, backend=backend))
    return written
