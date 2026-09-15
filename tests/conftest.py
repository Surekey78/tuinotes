"""Shared fixtures: an isolated vault per test."""

from __future__ import annotations

import pytest

from tuinotes.config import Config
from tuinotes.storage import NoteStore


@pytest.fixture(autouse=True)
def isolated_environment(tmp_path, monkeypatch):
    """Never read or write the developer's real config/vault."""
    monkeypatch.delenv("TUINOTES_HOME", raising=False)
    monkeypatch.delenv("TUINOTES_CONFIG", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg-config"))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("TERM", "xterm-256color")


@pytest.fixture
def config(tmp_path) -> Config:
    cfg = Config(notes_dir=str(tmp_path / "vault"))
    cfg.list.page_size = 50
    return cfg


@pytest.fixture
def store(config):
    note_store = NoteStore(config, min_sync_interval=0.0)
    note_store.ensure_dirs()
    yield note_store
    note_store.close()


@pytest.fixture
def seeded(store):
    """Three linked, tagged notes to exercise lists, search and the graph."""
    store.create(
        title="Rust async notes",
        content="Tokio makes async Rust ergonomic.\n\n#rust #programming\n",
        tags=[],
    )
    store.create(
        title="Tokio deep dive",
        content="See [[Rust async notes]] for the basics.\n\n#rust #reading\n",
    )
    store.create(
        title="Groceries",
        content="- [ ] milk\n- [ ] eggs\n\n#shopping\n",
    )
    return store


def write_note(store: NoteStore, name: str, body: str) -> str:
    """Write a note file directly (bypassing the store) to test re-indexing."""
    path = store.root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return name
