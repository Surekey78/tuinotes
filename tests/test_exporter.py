"""Export to HTML / Markdown / plain text, and PDF backend detection."""

from __future__ import annotations

from pathlib import Path

import pytest

from tuinotes import exporter
from tuinotes.models import NoteRef


@pytest.fixture
def note(store):
    return store.create(
        title="Export me",
        content="# Export me\n\nSome **bold** text and a [link](https://example.com).\n\n#demo\n",
    )


def test_html_contains_title_meta_and_body(note):
    html = exporter.markdown_to_html(note)
    assert "<title>Export me</title>" in html
    assert "Export me" in html
    assert "#demo" in html
    assert "words" in html  # metadata line
    assert "<style>" in html and "{ color-scheme: dark; }" in html


def test_html_escapes_dangerous_content(store):
    note = store.create(title="XSS <script>", content="<script>alert(1)</script>")
    html = exporter.markdown_to_html(note)
    assert "<title>XSS &lt;script&gt;</title>" in html


def test_export_formats(note, tmp_path):
    for fmt in ("html", "md", "txt"):
        target = tmp_path / f"out.{fmt}"
        written = exporter.export_note(note, target, fmt=fmt)
        assert written.is_file() and written.stat().st_size > 0
    assert (tmp_path / "out.md").read_text(encoding="utf-8").startswith("# Export me")
    assert "**bold**" not in (tmp_path / "out.txt").read_text(encoding="utf-8")


def test_unknown_format_is_rejected(note, tmp_path):
    with pytest.raises(exporter.ExportError):
        exporter.export_note(note, tmp_path / "out.docx", fmt="docx")


def test_pdf_without_a_backend_explains_itself(note, tmp_path, monkeypatch):
    monkeypatch.setattr(exporter, "pdf_backend", lambda backend="auto": None)
    with pytest.raises(exporter.ExportError) as error:
        exporter.export_note(note, tmp_path / "out.pdf", fmt="pdf")
    assert "pandoc" in str(error.value)


def test_pdf_backend_prefers_pandoc(monkeypatch):
    monkeypatch.setattr(exporter.shutil, "which", lambda name: "/usr/bin/pandoc")
    assert exporter.pdf_backend("auto") == "pandoc"


def test_export_many(note, store, tmp_path):
    store.create(title="Second", content="more")
    notes = [store.get(ref.path) for ref in store.list_notes()]
    written = exporter.export_many(notes, tmp_path / "all", fmt="html")
    assert len(written) == 2
    assert all(path.suffix == ".html" and path.is_file() for path in written)


def test_default_export_path_uses_the_stem():
    ref = NoteRef(path="2026-09-15-my-note.md", title="My note")
    target = exporter.default_export_path(ref, "html", Path("/tmp/out"))
    assert target == Path("/tmp/out/2026-09-15-my-note.html")
