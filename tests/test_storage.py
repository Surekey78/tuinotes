"""The vault: files on disk plus the SQLite index."""

from __future__ import annotations

import time

import pytest

from tuinotes.models import SORT_ALPHABETICAL, SORT_NEWEST, SORT_OLDEST
from tuinotes.storage import NoteNotFound

from .conftest import write_note


def test_create_writes_a_markdown_file(store):
    note = store.create(title="First note", content="hello world")
    path = store.root / note.ref.path
    assert path.is_file()
    assert path.read_text(encoding="utf-8").startswith("# First note")
    assert note.ref.path.endswith(".md")
    assert "first-note" in note.ref.path.lower()
    assert store.exists(note.ref.path)


def test_quick_capture_keeps_content_verbatim(store):
    note = store.create(content="buy milk and eggs #shopping")
    assert (store.root / note.ref.path).read_text(encoding="utf-8") == (
        "buy milk and eggs #shopping\n"
    )
    assert note.ref.title == "buy milk and eggs"
    assert note.ref.tags == ("shopping",)


def test_filenames_are_date_prefixed_and_unique(store):
    first = store.create(title="Same title")
    second = store.create(title="Same title")
    assert first.ref.path != second.ref.path
    assert second.ref.path.endswith("-2.md")
    assert first.ref.path.startswith(time.strftime("%Y-%m-%d"))


def test_update_rewrites_the_file_and_the_index(store):
    note = store.create(title="Draft", content="original")
    updated = store.update(note, "changed body #tagged")
    assert (store.root / updated.ref.path).read_text(encoding="utf-8").startswith("changed body")
    assert updated.ref.tags == ("tagged",)
    assert updated.ref.word_count == 3  # "changed body #tagged"


def test_atomic_write_leaves_no_temp_files(store):
    note = store.create(title="Durable", content="x")
    store.update(note, "y")
    leftovers = [p.name for p in store.root.iterdir() if ".tmp" in p.name]
    assert leftovers == []


def test_list_sorts(store, seeded):
    assert [r.title for r in seeded.list_notes(sort=SORT_ALPHABETICAL)] == [
        "Groceries",
        "Rust async notes",
        "Tokio deep dive",
    ]
    newest = seeded.list_notes(sort=SORT_NEWEST)
    oldest = seeded.list_notes(sort=SORT_OLDEST)
    assert newest[0].path == oldest[-1].path


def test_pagination(store):
    for index in range(5):
        store.create(title=f"Note {index}", content="body")
    page = store.list_notes(limit=2, offset=2)
    assert len(page) == 2
    assert len(store.list_notes()) == 5


def test_tag_filter_is_case_insensitive(seeded):
    assert {r.title for r in seeded.list_notes(tags=["RUST"])} == {
        "Rust async notes",
        "Tokio deep dive",
    }
    assert {r.title for r in seeded.list_notes(tags=["rust"], exclude_tags=["reading"])} == {
        "Rust async notes"
    }


def test_search_finds_body_text_and_typos(seeded):
    hits = seeded.search("tokio")
    assert hits and hits[0].ref.title in {"Tokio deep dive", "Rust async notes"}
    fuzzy = seeded.search("grocer")
    assert fuzzy and fuzzy[0].ref.title == "Groceries"


def test_search_tag_syntax(seeded):
    assert {r.ref.title for r in seeded.search("#reading")} == {"Tokio deep dive"}
    assert {r.ref.title for r in seeded.search("#rust -#reading")} == {"Rust async notes"}


def test_resolve_by_path_stem_and_title(seeded):
    ref = seeded.list_notes(sort=SORT_ALPHABETICAL)[0]
    assert seeded.resolve(ref.path).path == ref.path
    assert seeded.resolve(ref.path[:-3]).path == ref.path
    assert seeded.resolve("Groceries").path == ref.path
    with pytest.raises(NoteNotFound):
        seeded.resolve("definitely-not-here-xyz")


def test_trash_restore_and_purge(store, seeded):
    ref = seeded.resolve("Groceries")
    trash_name = store.delete(ref)
    assert trash_name
    assert not store.exists(ref.path)
    assert not (store.root / ref.path).exists()
    assert (store.trash_dir / trash_name).is_file()

    entries = store.list_trash()
    assert [entry.title for entry in entries] == ["Groceries"]

    restored = store.restore(trash_name)
    assert restored.path == ref.path
    assert store.exists(ref.path)
    assert store.list_trash() == []

    store.delete(store.resolve("Groceries"))
    assert store.purge_trash(days=0) == 1
    assert store.list_trash() == []


def test_rename_updates_wikilinks(store):
    store.create(title="Original Title", content="body")
    other = store.create(title="Referrer", content="see [[Original Title]] now")
    renamed = store.rename(store.resolve("Original Title"), "New Title")
    assert renamed.ref.title == "New Title"
    body = store.read_content(other.ref.path)
    assert "[[New Title]]" in body
    assert "[[Original Title]]" not in body


def test_external_files_are_indexed_and_deletions_noticed(store):
    write_note(store, "external.md", "# External\n\nwritten by hand #manual\n")
    store.sync(force=True)
    assert store.exists("external.md")
    assert store.resolve("external.md").tags == ("manual",)

    (store.root / "external.md").unlink()
    store.sync(force=True)
    assert not store.exists("external.md")


def test_hidden_directories_are_ignored(store):
    (store.root / ".trash").mkdir(exist_ok=True)
    write_note(store, ".trash/20260101-000000-abcdef-gone.md", "# gone\n")
    write_note(store, ".templates/ignored.md", "# template\n")
    store.reindex()
    assert not store.exists(".trash/20260101-000000-abcdef-gone.md")
    assert store.count() == 0


def test_backlinks_and_outgoing(store):
    store.create(title="Target", content="hi")
    store.create(title="Source", content="link to [[Target]]")
    target = store.resolve("Target")
    assert [r.title for r in store.backlinks(target)] == ["Source"]
    source = store.resolve("Source")
    assert [(link, bool(resolved)) for link, resolved in store.outgoing(source)] == [
        ("Target", True)
    ]


def test_daily_note_is_stable_and_idempotent(store):
    first = store.daily_note()
    assert first.ref.path == time.strftime("%Y-%m-%d") + ".md"
    second = store.daily_note()
    assert second.ref.path == first.ref.path
    assert store.count() == 1


def test_templates_render_into_new_notes(store):
    note = store.create(template="meeting", title="Standup")
    body = store.read_content(note.ref.path)
    assert "# Meeting: Standup" in body
    assert "#meeting" in body


def test_stats_and_tag_counts(seeded):
    stats = seeded.stats()
    assert stats["notes"] == 3
    assert stats["tags"] == 4
    assert stats["linked"] == 1
    assert dict(seeded.tag_counts())["rust"] == 2


def test_index_survives_a_rebuild(store, seeded):
    assert seeded.reindex() == 3
    assert seeded.count() == 3
    assert seeded.search("tokio")


def test_performance_with_many_notes(store):
    start = time.time()
    for index in range(300):
        store.create(title=f"Note {index:03d}", content=f"body text {index} #batch")
    indexed = time.time() - start
    start = time.time()
    rows = store.list_notes(limit=50)
    listed = time.time() - start
    assert len(rows) == 50
    assert indexed < 30, indexed
    assert listed < 1.0, listed
    assert store.count() == 300


def test_encrypted_notes_are_not_indexed(store, monkeypatch):
    """A ``.md.gpg`` file is listed but its body never reaches the index."""
    write_note(store, "secret.md.gpg", "binary-ish gpg payload")
    store.sync(force=True)
    ref = store.resolve("secret")
    assert ref.encrypted
    assert ref.preview == "Encrypted note"
    assert store.search("payload") == []
