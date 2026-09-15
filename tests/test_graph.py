"""Link graph construction and ASCII rendering."""

from __future__ import annotations

from tuinotes.graph import LinkGraph
from tuinotes.models import NoteRef


def make(path: str, title: str, links=()) -> NoteRef:
    return NoteRef(path=path, title=title, links=tuple(links))


NOTES = [
    make("a.md", "Alpha", links=["Beta"]),
    make("b.md", "Beta", links=["Gamma"]),
    make("c.md", "Gamma"),
    make("d.md", "Delta", links=["Missing"]),
    make("e.md", "Lonely"),
]


def test_edges_resolve_by_title():
    graph = LinkGraph.build(NOTES)
    assert graph.outgoing("a.md") == ["b.md"]
    assert graph.backlinks("b.md") == ["a.md"]
    assert graph.neighbors("b.md") == ["a.md", "c.md"]


def test_unresolved_links_are_tracked():
    graph = LinkGraph.build(NOTES)
    assert graph.unresolved["d.md"] == {"Missing"}


def test_components_and_orphans():
    graph = LinkGraph.build(NOTES)
    components = graph.components()
    assert ["a.md", "b.md", "c.md"] in components
    # Delta only links to a note that does not exist, so it is unlinked too.
    assert graph.orphans() == ["d.md", "e.md"]


def test_subgraph_limits_depth():
    graph = LinkGraph.build(NOTES)
    sub = graph.subgraph("a.md", depth=1)
    assert set(sub.nodes) == {"a.md", "b.md"}
    deep = graph.subgraph("a.md", depth=2)
    assert set(deep.nodes) == {"a.md", "b.md", "c.md"}


def test_render_text_shows_clusters_orphans_and_missing_targets():
    text = LinkGraph.build(NOTES).render_text(width=80).plain
    assert "cluster 1" in text
    assert "Alpha ──▶ Beta" in text
    assert "Lonely" in text
    assert "Missing link targets" in text
    assert "[[Missing]]" in text


def test_render_text_without_links():
    graph = LinkGraph.build([make("solo.md", "Solo")])
    rendered = graph.render_text().plain
    assert "No links yet" in rendered
    assert "Solo" in rendered


def test_render_text_without_notes():
    assert "No notes yet" in LinkGraph.build([]).render_text().plain


def test_stats():
    stats = LinkGraph.build(NOTES).stats()
    assert stats["notes"] == 5
    assert stats["links"] == 2
    assert stats["orphans"] == 2
    assert stats["unresolved"] == 1


def test_exclude_orphans():
    graph = LinkGraph.build(NOTES, include_orphans=False)
    assert "e.md" not in graph.nodes
