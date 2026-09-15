"""Backlink graph: connected components and an ASCII rendering of them.

The graph is derived purely from ``[[wikilinks]]`` already indexed by the store,
so it costs nothing extra and works offline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Sequence, Set, Tuple

from rich.text import Text

from tuinotes.models import NoteRef

EDGE_STYLE = "cyan"
NODE_STYLE = "bold"
ORPHAN_STYLE = "dim"


@dataclass
class LinkGraph:
    """Directed graph of note links with helper queries."""

    nodes: Dict[str, NoteRef] = field(default_factory=dict)
    edges: Dict[str, Set[str]] = field(default_factory=dict)
    unresolved: Dict[str, Set[str]] = field(default_factory=dict)

    # ------------------------------------------------------------------ build
    @classmethod
    def build(cls, refs: Sequence[NoteRef], *, include_orphans: bool = True) -> LinkGraph:
        graph = cls()
        by_title: Dict[str, NoteRef] = {}
        for ref in refs:
            graph.nodes[ref.path] = ref
            graph.edges.setdefault(ref.path, set())
            by_title.setdefault(ref.title.lower(), ref)
            by_title.setdefault(ref.stem.lower(), ref)
        for ref in refs:
            for link in ref.links:
                target = by_title.get(link.lower())
                if target is None:
                    graph.unresolved.setdefault(ref.path, set()).add(link)
                    continue
                if target.path == ref.path:
                    continue
                graph.edges[ref.path].add(target.path)
        if not include_orphans:
            linked = {path for path, outs in graph.edges.items() if outs}
            linked |= {to for outs in graph.edges.values() for to in outs}
            graph.nodes = {path: ref for path, ref in graph.nodes.items() if path in linked}
            graph.edges = {path: outs for path, outs in graph.edges.items() if path in graph.nodes}
        return graph

    # ------------------------------------------------------------------ queries
    def backlinks(self, path: str) -> List[str]:
        return sorted(source for source, outs in self.edges.items() if path in outs)

    def outgoing(self, path: str) -> List[str]:
        return sorted(self.edges.get(path, set()))

    def neighbors(self, path: str) -> List[str]:
        return sorted(set(self.outgoing(path)) | set(self.backlinks(path)))

    def is_orphan(self, path: str) -> bool:
        return not self.neighbors(path)

    def orphans(self) -> List[str]:
        return [path for path in sorted(self.nodes) if self.is_orphan(path)]

    def components(self) -> List[List[str]]:
        """Weakly connected components, largest first."""
        adjacency: Dict[str, Set[str]] = {path: set() for path in self.nodes}
        for source, targets in self.edges.items():
            if source not in adjacency:
                continue
            for target in targets:
                if target in adjacency:
                    adjacency[source].add(target)
                    adjacency[target].add(source)
        seen: Set[str] = set()
        components: List[List[str]] = []
        for start in sorted(adjacency):
            if start in seen:
                continue
            stack = [start]
            component: List[str] = []
            while stack:
                node = stack.pop()
                if node in seen:
                    continue
                seen.add(node)
                component.append(node)
                stack.extend(adjacency[node] - seen)
            components.append(sorted(component))
        components.sort(key=lambda part: (-len(part), part[0]))
        return components

    def subgraph(self, path: str, depth: int = 1) -> LinkGraph:
        """Notes within ``depth`` hops of ``path`` (for the TUI graph screen)."""
        depth = max(1, depth)
        wanted: Set[str] = {path}
        frontier = {path}
        for _ in range(depth):
            nxt: Set[str] = set()
            for node in frontier:
                nxt |= set(self.neighbors(node))
            nxt -= wanted
            wanted |= nxt
            frontier = nxt
        sub = LinkGraph()
        sub.nodes = {p: self.nodes[p] for p in wanted if p in self.nodes}
        sub.edges = {
            source: {t for t in targets if t in sub.nodes}
            for source, targets in self.edges.items()
            if source in sub.nodes
        }
        sub.unresolved = {
            source: set(links) for source, links in self.unresolved.items() if source in sub.nodes
        }
        return sub

    # ----------------------------------------------------------------- render
    def edge_list(self) -> List[Tuple[str, str]]:
        return [
            (source, target)
            for source in sorted(self.edges)
            for target in sorted(self.edges[source])
        ]

    def render_text(self, *, max_components: int = 40, width: int = 78) -> Text:
        """A compact ASCII picture: one boxed cluster per component."""
        text = Text()
        components = self.components()
        linked = [part for part in components if any(self.edges.get(p) for p in part)]
        orphan_paths = self.orphans()
        missing = [
            (path, link)
            for path in sorted(self.unresolved)
            for link in sorted(self.unresolved[path])
        ]
        if not self.nodes:
            text.append("No notes yet.\n", ORPHAN_STYLE)
            return text
        if not linked and not missing:
            text.append("No links yet — connect notes with [[double brackets]].\n", ORPHAN_STYLE)

        for index, component in enumerate(linked[:max_components]):
            rows = [self._component_line(path, width - 6) for path in component]
            rows += [
                f" {self.nodes[path].title} ──▶ [[{link}]] (missing)"
                for path in component
                for link in sorted(self.unresolved.get(path, set()))
            ]
            header = f" cluster {index + 1}: {len(component)} notes "
            inner = min(max(len(header), *(len(row) for row in rows) if rows else [20]), width - 2)
            header_line = header.ljust(inner, "─")[:inner]
            text.append("┌" + header_line + "┐\n", EDGE_STYLE)
            for row in rows:
                text.append(row.rstrip().ljust(inner) + "\n", NODE_STYLE)
            text.append("└" + "─" * inner + "┘\n\n", EDGE_STYLE)

        if len(linked) > max_components:
            text.append(f"… {len(linked) - max_components} more clusters\n", ORPHAN_STYLE)
        if missing:
            text.append(f"Missing link targets ({len(missing)}):\n", "yellow")
            for path, link in missing[:25]:
                text.append(
                    _truncate(f"  {self.nodes[path].title} ──▶ [[{link}]]", width) + "\n",
                    "dim yellow",
                )
        if orphan_paths:
            text.append(f"Unlinked notes ({len(orphan_paths)}):\n", ORPHAN_STYLE)
            names = ", ".join(self.nodes[path].title for path in orphan_paths[:25])
            if len(orphan_paths) > 25:
                names += f", … (+{len(orphan_paths) - 25})"
            text.append("  " + names + "\n", ORPHAN_STYLE)
        return text

    def stats(self) -> Dict[str, object]:
        return {
            "notes": len(self.nodes),
            "links": sum(len(outs) for outs in self.edges.values()),
            "clusters": len([c for c in self.components() if any(self.edges.get(p) for p in c)]),
            "orphans": len(self.orphans()),
            "unresolved": sum(len(links) for links in self.unresolved.values()),
        }


    def _component_line(self, path: str, width: int) -> str:
        """One (possibly multi-line) row of the cluster box."""
        ref = self.nodes[path]
        targets = sorted(self.edges.get(path, set()))
        lines: list = []
        if targets:
            for offset, target in enumerate(targets):
                title = self.nodes[target].title
                if offset == 0:
                    lines.append(f" {ref.title} ──▶ {title}")
                else:
                    lines.append(" " * (len(ref.title) + 1) + f" └─▶ {title}")
        else:
            incoming = self.backlinks(path)
            if incoming:
                names = ", ".join(self.nodes[item].title for item in incoming[:4])
                lines.append(f" {ref.title} ◀── {names}")
            else:
                lines.append(f" {ref.title}")
        return "\n".join(_truncate(line, width) for line in lines)


def _truncate(line: str, width: int) -> str:
    if width <= 1 or len(line) <= width:
        return line
    return line[: max(0, width - 1)] + "…"


def build_from_refs(refs: Iterable[NoteRef], *, include_orphans: bool = True) -> LinkGraph:
    return LinkGraph.build(list(refs), include_orphans=include_orphans)
