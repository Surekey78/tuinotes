"""Data model: :class:`NoteRef` (index row) and :class:`Note` (ref + content).

The split matters for performance: listing and searching 1000+ notes never
touches note bodies, because :class:`NoteRef` is fully served from SQLite.
"""

from __future__ import annotations

import dataclasses
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

SORT_MODIFIED = "modified"
SORT_NEWEST = "newest"
SORT_OLDEST = "oldest"
SORT_ALPHABETICAL = "alphabetical"
SORT_SIZE = "size"

SORT_LABELS: Dict[str, str] = {
    SORT_MODIFIED: "modified",
    SORT_NEWEST: "newest",
    SORT_OLDEST: "oldest",
    SORT_ALPHABETICAL: "a→z",
    SORT_SIZE: "size",
}

DEFAULT_TITLE = "Untitled"


@dataclasses.dataclass(frozen=True)
class NoteRef:
    """Metadata for a single note, straight from the SQLite index."""

    path: str
    title: str = DEFAULT_TITLE
    preview: str = ""
    created: float = 0.0
    modified: float = 0.0
    word_count: int = 0
    char_count: int = 0
    size: int = 0
    tags: Tuple[str, ...] = ()
    links: Tuple[str, ...] = ()
    encrypted: bool = False

    # -- identity ---------------------------------------------------------
    @property
    def id(self) -> str:
        """Stable identifier (the vault-relative path)."""
        return self.path

    @property
    def name(self) -> str:
        return Path(self.path).name

    @property
    def stem(self) -> str:
        """File name without ``.md`` (and without a trailing ``.gpg``)."""
        name = Path(self.path).name
        if name.lower().endswith(".gpg"):
            name = name[: -len(".gpg")]
        for suffix in (".markdown", ".md"):
            if name.lower().endswith(suffix):
                return name[: -len(suffix)]
        return name

    @property
    def folder(self) -> str:
        parent = str(Path(self.path).parent)
        return "" if parent == "." else parent

    # -- timestamps -------------------------------------------------------
    @property
    def created_dt(self) -> datetime:
        return datetime.fromtimestamp(self.created) if self.created else datetime.now()

    @property
    def modified_dt(self) -> datetime:
        return datetime.fromtimestamp(self.modified) if self.modified else datetime.now()

    def relative_time(self, now: Optional[float] = None) -> str:
        """Human, phone-sized timestamp: ``now``, ``5m``, ``3h``, ``2d``, ``Mar 3``."""
        return relative_time(self.modified or self.created, now)

    def date_str(self, fmt: str = "%Y-%m-%d") -> str:
        return self.modified_dt.strftime(fmt)

    # -- presentation -----------------------------------------------------
    @property
    def tag_str(self) -> str:
        return " ".join(f"#{tag}" for tag in self.tags)

    def summary(self) -> str:
        parts = [f"{self.word_count}w"]
        if self.encrypted:
            parts.insert(0, "🔒")
        if self.links:
            parts.append(f"{len(self.links)}↗")
        return " ".join(parts)

    def to_dict(self) -> Dict[str, Any]:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> NoteRef:
        tags = data.get("tags") or ()
        links = data.get("links") or ()
        if isinstance(tags, str):
            tags = tuple(t for t in tags.split() if t)
        if isinstance(links, str):
            links = tuple(t for t in links.split("\x1f") if t)
        return cls(
            path=str(data.get("path", "")),
            title=data.get("title") or DEFAULT_TITLE,
            preview=data.get("preview") or "",
            created=float(data.get("created") or 0.0),
            modified=float(data.get("modified") or 0.0),
            word_count=int(data.get("word_count") or 0),
            char_count=int(data.get("char_count") or 0),
            size=int(data.get("size") or 0),
            tags=tuple(tags),
            links=tuple(links),
            encrypted=bool(data.get("encrypted")),
        )


@dataclasses.dataclass
class Note:
    """A note with its content loaded."""

    ref: NoteRef
    content: str = ""

    # -- convenience pass-throughs ---------------------------------------
    @property
    def path(self) -> str:
        return self.ref.path

    @property
    def title(self) -> str:
        return self.ref.title

    @property
    def tags(self) -> Tuple[str, ...]:
        return self.ref.tags

    @property
    def links(self) -> Tuple[str, ...]:
        return self.ref.links

    @property
    def encrypted(self) -> bool:
        return self.ref.encrypted

    @property
    def word_count(self) -> int:
        return self.ref.word_count

    @property
    def char_count(self) -> int:
        return self.ref.char_count

    @property
    def created(self) -> float:
        return self.ref.created

    @property
    def modified(self) -> float:
        return self.ref.modified

    def abs_path(self, root: Path) -> Path:
        return root / self.ref.path

    def with_content(self, content: str) -> Note:
        return Note(ref=self.ref, content=content)


LINK_SEPARATOR = "\x1f"


def relative_time(timestamp: float, now: Optional[float] = None) -> str:
    """Compact relative time used in the note list."""
    if not timestamp:
        return "—"
    now = now if now is not None else time.time()
    delta = max(0, int(now - timestamp))
    if delta < 45:
        return "now"
    if delta < 3600:
        return f"{delta // 60}m"
    if delta < 86400:
        return f"{delta // 3600}h"
    if delta < 86400 * 7:
        return f"{delta // 86400}d"
    return datetime.fromtimestamp(timestamp).strftime("%b %d")


_SORTERS: Dict[str, Callable[[NoteRef], Any]] = {
    SORT_MODIFIED: lambda n: -(n.modified or 0.0),
    SORT_NEWEST: lambda n: -(n.created or 0.0),
    SORT_OLDEST: lambda n: (n.created or 0.0),
    SORT_ALPHABETICAL: lambda n: (n.title.lower(), n.path),
    SORT_SIZE: lambda n: -int(n.size or 0),
}


def sort_notes(refs: List[NoteRef], key: str = SORT_MODIFIED) -> List[NoteRef]:
    """Sort note refs by a named key (unknown keys fall back to ``modified``)."""
    sorter = _SORTERS.get(key, _SORTERS[SORT_MODIFIED])
    return sorted(refs, key=sorter)


def next_sort_key(key: str) -> str:
    """Cycle through the sort orders (bound to ``s`` in the note list)."""
    order = [SORT_MODIFIED, SORT_NEWEST, SORT_OLDEST, SORT_ALPHABETICAL, SORT_SIZE]
    if key not in order:
        return order[0]
    return order[(order.index(key) + 1) % len(order)]


def unique_tags(refs: List[NoteRef]) -> List[Tuple[str, int]]:
    """``[(tag, count)]`` sorted by popularity then name."""
    counts: Dict[str, int] = {}
    for ref in refs:
        for tag in ref.tags:
            counts[tag] = counts.get(tag, 0) + 1
    return sorted(counts.items(), key=lambda item: (-item[1], item[0].lower()))


@dataclasses.dataclass(frozen=True)
class TrashEntry:
    """A note sitting in ``.trash`` awaiting purge or restore."""

    path: str
    original_path: str
    deleted: float
    title: str = DEFAULT_TITLE

    @property
    def age_days(self) -> float:
        return max(0.0, (time.time() - self.deleted) / 86400.0)

    def relative_time(self) -> str:
        return relative_time(self.deleted)
