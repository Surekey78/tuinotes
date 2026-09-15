"""The note store: Markdown files on disk + a SQLite metadata index.

Design notes
------------
* **Files are the truth.** ``.md`` files under the vault are authoritative; the
  SQLite database (``.metadata.db``) is a rebuildable index. ``tuinotes
  reindex`` (or deleting the db file) always recovers.
* **Atomic writes.** Every save goes to a temp file, is flushed+fsynced, then
  ``os.replace``d into place, so a crashed editor can never truncate a note.
* **No body reads for lists.** Listing/searching 1000+ notes only touches the
  index, which keeps the app instant on a 2 GB phone.
* **Thread friendly.** The Textual UI runs workers in threads; a single
  connection guarded by a lock keeps SQLite happy.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import sqlite3
import threading
import time
from datetime import date as date_cls
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple, cast

from tuinotes import markdown_utils as md
from tuinotes.config import Config, load_config
from tuinotes.models import (
    DEFAULT_TITLE,
    LINK_SEPARATOR,
    SORT_ALPHABETICAL,
    SORT_MODIFIED,
    SORT_NEWEST,
    SORT_OLDEST,
    SORT_SIZE,
    Note,
    NoteRef,
    TrashEntry,
    sort_notes,
)
from tuinotes.search import (
    ParsedQuery,
    SearchResult,
    best_field_score,
    fuzzy_score,
    matches_tags,
    parse_query,
    rank,
    snippet_around,
)

NOTE_SUFFIXES = (".md", ".markdown", ".md.gpg", ".markdown.gpg")
ENCRYPTED_SUFFIX = ".gpg"
Hook = Callable[[str, Optional[NoteRef]], None]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS notes (
    path        TEXT PRIMARY KEY,
    title       TEXT NOT NULL DEFAULT '',
    preview     TEXT NOT NULL DEFAULT '',
    created     REAL NOT NULL DEFAULT 0,
    modified    REAL NOT NULL DEFAULT 0,
    word_count  INTEGER NOT NULL DEFAULT 0,
    char_count  INTEGER NOT NULL DEFAULT 0,
    size        INTEGER NOT NULL DEFAULT 0,
    tags        TEXT NOT NULL DEFAULT '',
    links       TEXT NOT NULL DEFAULT '',
    encrypted   INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_notes_modified ON notes(modified DESC);
CREATE INDEX IF NOT EXISTS idx_notes_created ON notes(created DESC);
CREATE INDEX IF NOT EXISTS idx_notes_title ON notes(title COLLATE NOCASE);
CREATE TABLE IF NOT EXISTS trash (
    path          TEXT PRIMARY KEY,
    original_path TEXT NOT NULL,
    deleted       REAL NOT NULL,
    title         TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""

_FTS_SCHEMA = (
    "CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5("
    "path UNINDEXED, title, preview, body, tags, "
    "tokenize=\"porter unicode61 remove_diacritics 2\")"
)

_ORDER_BY = {
    SORT_MODIFIED: "modified DESC",
    SORT_NEWEST: "created DESC",
    SORT_OLDEST: "created ASC",
    SORT_ALPHABETICAL: "title COLLATE NOCASE ASC, path ASC",
    SORT_SIZE: "size DESC",
}

_ROW_TO_REF = "path, title, preview, created, modified, word_count, char_count, size, tags, links, encrypted"


class StorageError(Exception):
    """Raised when the vault cannot satisfy an operation."""


class NoteNotFound(StorageError):
    """Raised when a note path/title cannot be resolved."""


def _fts_available(connection: sqlite3.Connection) -> bool:
    try:
        connection.execute("CREATE VIRTUAL TABLE IF NOT EXISTS _fts_probe USING fts5(x)")
        connection.execute("DROP TABLE IF EXISTS _fts_probe")
        return True
    except sqlite3.OperationalError:  # pragma: no cover - depends on sqlite build
        return False


class NoteStore:
    """Markdown vault + SQLite index."""

    def __init__(self, config: Optional[Config] = None, *, min_sync_interval: float = 1.5) -> None:
        self.config = config or load_config()
        self.root: Path = self.config.root
        self.db_path: Path = self.config.metadata_db
        self.trash_dir: Path = self.config.trash_dir
        self._lock = threading.RLock()
        self._conn: Optional[sqlite3.Connection] = None
        self._has_fts: bool = False
        self._last_sync: float = 0.0
        self._min_sync_interval = min_sync_interval
        self._cache: Dict[str, object] = {}
        self._hooks: List[Hook] = []

    # ------------------------------------------------------------------ setup
    def ensure_dirs(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.trash_dir.mkdir(parents=True, exist_ok=True)
        self.config.templates_dir_path.mkdir(parents=True, exist_ok=True)

    @property
    def connection(self) -> sqlite3.Connection:
        if self._conn is None:
            self.ensure_dirs()
            conn = sqlite3.connect(str(self.db_path), check_same_thread=False, timeout=10.0)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA temp_store=MEMORY")
            conn.executescript(_SCHEMA)
            self._has_fts = _fts_available(conn)
            if self._has_fts:
                conn.execute(_FTS_SCHEMA)
            conn.commit()
            self._conn = conn
        return self._conn

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.commit()
                self._conn.close()
                self._conn = None

    def add_hook(self, hook: Hook) -> None:
        """Register ``hook(event, ref)``; events: created/updated/deleted/restored."""
        self._hooks.append(hook)

    def _fire(self, event: str, ref: Optional[NoteRef] = None) -> None:
        for hook in list(self._hooks):
            try:
                hook(event, ref)
            except Exception:  # pragma: no cover - a bad hook must not break saves
                pass

    # ---------------------------------------------------------------- scanning
    def walk_files(self) -> Iterable[Path]:
        """Yield note files, skipping hidden directories (``.trash``, ...)."""
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            for name in filenames:
                lowered = name.lower()
                if not lowered.endswith(NOTE_SUFFIXES) or name.startswith("."):
                    continue
                yield Path(dirpath) / name

    def _rel(self, path: Path) -> str:
        try:
            return path.relative_to(self.root).as_posix()
        except ValueError:  # pragma: no cover - outside the vault
            return path.name

    def sync(self, force: bool = False) -> int:
        """Bring the index in line with the vault. Returns rows changed."""
        with self._lock:
            if not force and time.time() - self._last_sync < self._min_sync_interval:
                return 0
            conn = self.connection
            known: Dict[str, Tuple[float, int]] = {
                row["path"]: (row["modified"], row["size"])
                for row in conn.execute("SELECT path, modified, size FROM notes")
            }
            seen: set = set()
            changed = 0
            for path in self.walk_files():
                rel = self._rel(path)
                seen.add(rel)
                try:
                    stat = path.stat()
                except OSError:
                    continue
                previous = known.get(rel)
                if (
                    previous is not None
                    and abs(previous[0] - stat.st_mtime) < 0.001
                    and previous[1] == stat.st_size
                ):
                    continue
                self._index_file(path, conn, stat=stat)
                changed += 1
            stale = [path for path in known if path not in seen]
            for rel in stale:
                self._delete_rows(rel, conn)
                changed += 1
            conn.commit()
            self._last_sync = time.time()
            self._cache.clear()
            return changed

    def reindex(self) -> int:
        """Rebuild the index from scratch."""
        with self._lock:
            conn = self.connection
            conn.execute("DELETE FROM notes")
            if self._has_fts:
                conn.execute("DELETE FROM notes_fts")
            conn.commit()
            count = 0
            for path in self.walk_files():
                self._index_file(path, conn)
                count += 1
            conn.commit()
            self._cache.clear()
            self._last_sync = time.time()
            return count

    def _index_file(
        self, path: Path, conn: sqlite3.Connection, stat: Optional[os.stat_result] = None
    ) -> NoteRef:
        rel = self._rel(path)
        stat = stat or path.stat()
        encrypted = rel.lower().endswith(ENCRYPTED_SUFFIX)
        created = self._previous_created(rel, conn) or stat.st_mtime
        if encrypted:
            ref = NoteRef(
                path=rel,
                title=md.extract_title(path.stem.replace(".md", "")) or DEFAULT_TITLE,
                preview="Encrypted note",
                created=created,
                modified=stat.st_mtime,
                word_count=0,
                char_count=0,
                size=stat.st_size,
                encrypted=True,
            )
            body = ""
        else:
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:  # pragma: no cover - permission oddities
                raise StorageError(f"cannot read {path}: {exc}") from exc
            title = md.extract_title(text) or path.stem
            tags = tuple(md.extract_tags(text))
            links = tuple(md.extract_links(text))
            ref = NoteRef(
                path=rel,
                title=title,
                preview=md.extract_preview(text, self.config.list.max_snippet),
                created=created,
                modified=stat.st_mtime,
                word_count=md.count_words(text),
                char_count=md.count_chars(text),
                size=stat.st_size,
                tags=tags,
                links=links,
            )
            body = text
        self._upsert(ref, body, conn)
        return ref

    def _previous_created(self, rel: str, conn: sqlite3.Connection) -> float:
        row = conn.execute("SELECT created FROM notes WHERE path = ?", (rel,)).fetchone()
        return float(row["created"]) if row and row["created"] else 0.0

    def _upsert(self, ref: NoteRef, body: str, conn: sqlite3.Connection) -> None:
        tags_blob = "".join(f" {tag}" for tag in ref.tags) + (" " if ref.tags else "")
        conn.execute(
            """
            INSERT INTO notes (path, title, preview, created, modified, word_count,
                               char_count, size, tags, links, encrypted)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(path) DO UPDATE SET
                title=excluded.title, preview=excluded.preview, created=excluded.created,
                modified=excluded.modified, word_count=excluded.word_count,
                char_count=excluded.char_count, size=excluded.size, tags=excluded.tags,
                links=excluded.links, encrypted=excluded.encrypted
            """,
            (
                ref.path,
                ref.title,
                ref.preview,
                ref.created,
                ref.modified,
                ref.word_count,
                ref.char_count,
                ref.size,
                tags_blob,
                LINK_SEPARATOR.join(ref.links),
                1 if ref.encrypted else 0,
            ),
        )
        if self._has_fts:
            conn.execute("DELETE FROM notes_fts WHERE path = ?", (ref.path,))
            if body:
                conn.execute(
                    "INSERT INTO notes_fts (path, title, preview, body, tags) VALUES (?, ?, ?, ?, ?)",
                    (ref.path, ref.title, ref.preview, body, " ".join(ref.tags)),
                )

    def _delete_rows(self, rel: str, conn: Optional[sqlite3.Connection] = None) -> None:
        conn = conn or self.connection
        conn.execute("DELETE FROM notes WHERE path = ?", (rel,))
        if self._has_fts:
            conn.execute("DELETE FROM notes_fts WHERE path = ?", (rel,))

    # ------------------------------------------------------------------ reads
    def _row_to_ref(self, row: sqlite3.Row) -> NoteRef:
        tags = tuple(t for t in (row["tags"] or "").split() if t)
        links = tuple(t for t in (row["links"] or "").split(LINK_SEPARATOR) if t)
        return NoteRef(
            path=row["path"],
            title=row["title"] or DEFAULT_TITLE,
            preview=row["preview"] or "",
            created=float(row["created"] or 0.0),
            modified=float(row["modified"] or 0.0),
            word_count=int(row["word_count"] or 0),
            char_count=int(row["char_count"] or 0),
            size=int(row["size"] or 0),
            tags=tags,
            links=links,
            encrypted=bool(row["encrypted"]),
        )

    def all_refs(self, *, sync: bool = True) -> List[NoteRef]:
        """Every indexed note (sorted by modified desc). Cached until a write."""
        if sync:
            self.sync()
        with self._lock:
            cached = self._cache.get("all_refs")
            if isinstance(cached, list):
                return list(cast(List[NoteRef], cached))
            rows = self.connection.execute(f"SELECT {_ROW_TO_REF} FROM notes").fetchall()
            refs = sort_notes([self._row_to_ref(row) for row in rows], SORT_MODIFIED)
            self._cache["all_refs"] = refs
            return list(refs)

    def list_notes(
        self,
        sort: str = SORT_MODIFIED,
        tags: Sequence[str] = (),
        exclude_tags: Sequence[str] = (),
        folder: Optional[str] = None,
        query: Optional[str] = None,
        limit: Optional[int] = None,
        offset: int = 0,
        *,
        sync: bool = True,
    ) -> List[NoteRef]:
        """Page through notes with optional tag/folder filtering.

        Filtering and ordering happen in SQL so a 5 000-note vault still opens
        instantly; tag predicates are re-verified in Python to avoid ``LIKE``
        substring surprises.
        """
        if query:
            results = self.search(query, tags=tags, limit=(limit or 500) + offset)
            refs = [result.ref for result in results]
            return refs[offset : offset + limit] if limit else refs[offset:]

        if sync:
            self.sync()
        clauses: List[str] = []
        params: List[object] = []
        if folder:
            prefix = folder.strip("/") + "/"
            clauses.append("path LIKE ?")
            params.append(prefix + "%")
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        order = _ORDER_BY.get(sort, _ORDER_BY[SORT_MODIFIED])
        # Tag predicates are applied in Python (case-insensitively), so the SQL
        # LIMIT is only pushed down when no tag filter is involved.
        fetch_limit = None if (limit is None or tags or exclude_tags) else limit + offset
        sql = f"SELECT {_ROW_TO_REF} FROM notes{where} ORDER BY {order}"
        if fetch_limit is not None:
            sql += " LIMIT ?"
            params.append(fetch_limit)
        with self._lock:
            rows = self.connection.execute(sql, params).fetchall()
        refs = [self._row_to_ref(row) for row in rows]
        if tags or exclude_tags:
            refs = [
                ref for ref in refs if matches_tags(ref, tags, exclude_tags)
            ]
        return refs[offset : offset + limit] if limit else refs[offset:]

    def count(self, tags: Sequence[str] = (), folder: Optional[str] = None) -> int:
        if tags or folder:
            return len(self.list_notes(tags=tags, folder=folder))
        with self._lock:
            row = self.connection.execute("SELECT COUNT(*) AS n FROM notes").fetchone()
        return int(row["n"]) if row else 0

    def exists(self, path: str) -> bool:
        with self._lock:
            row = self.connection.execute(
                "SELECT 1 FROM notes WHERE path = ?", (path,)
            ).fetchone()
        return row is not None

    def resolve(self, needle: str) -> NoteRef:
        """Resolve a path, stem or title to a :class:`NoteRef`."""
        self.sync()
        needle = (needle or "").strip()
        if not needle:
            raise NoteNotFound("empty note reference")
        refs = self.all_refs(sync=False)
        by_path = {ref.path: ref for ref in refs}
        for candidate in (needle, needle if needle.endswith(".md") else needle + ".md"):
            if candidate in by_path:
                return by_path[candidate]
        lowered = needle.lower().strip("/")
        for ref in refs:
            if ref.path.lower() == lowered or ref.stem.lower() == lowered:
                return ref
        for ref in refs:
            if ref.title.lower() == needle.lower():
                return ref
        best: Optional[Tuple[float, NoteRef]] = None
        for ref in refs:
            score = fuzzy_score(lowered, ref.title.lower()) or fuzzy_score(lowered, ref.stem.lower())
            if score is not None and (best is None or score > best[0]):
                best = (score, ref)
        if best is not None and best[0] >= 0.45:
            return best[1]
        raise NoteNotFound(f"no note matching {needle!r}")

    def read_content(self, path: str, *, decrypt: bool = True) -> str:
        """Read a note's body from disk (never from the index)."""
        target = self.root / path
        if not target.is_file():
            resolved = self.resolve(path)
            target = self.root / resolved.path
        try:
            if target.name.lower().endswith(ENCRYPTED_SUFFIX):
                if not decrypt:
                    return ""
                from tuinotes import encryption

                return encryption.decrypt_text(target, self.config.encryption)
            return target.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            raise StorageError(f"cannot read {target}: {exc}") from exc

    def get(self, needle: str, *, decrypt: bool = True) -> Note:
        ref = self.resolve(needle) if not self.exists(needle) else self._ref_for(needle)
        return Note(ref=ref, content=self.read_content(ref.path, decrypt=decrypt))

    def _ref_for(self, path: str) -> NoteRef:
        with self._lock:
            row = self.connection.execute(
                f"SELECT {_ROW_TO_REF} FROM notes WHERE path = ?", (path,)
            ).fetchone()
        if row is None:
            raise NoteNotFound(path)
        return self._row_to_ref(row)

    # ------------------------------------------------------------------ writes
    def atomic_write(self, path: Path, text: str) -> None:
        """Write ``text`` durably: temp file → fsync → ``os.replace``."""
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f".{path.name}.tmp{os.getpid()}")
        try:
            with open(tmp, "w", encoding="utf-8") as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, path)
        finally:
            if tmp.exists():  # pragma: no cover - only on exotic failures
                try:
                    tmp.unlink()
                except OSError:
                    pass

    def new_path(self, title: str, folder: str = "", when: Optional[float] = None) -> str:
        """Build a collision-free vault-relative path for ``title``."""
        when = when if when is not None else time.time()
        stamp = datetime.fromtimestamp(when)
        slug = md.slugify(title) or "note"
        if self.config.filename_date_prefix:
            name = self.config.filename_format
            for key, value in (("{slug}", slug), ("{title}", slug)):
                name = name.replace(key, value)
            name = name.replace("{date}", stamp.strftime("%Y-%m-%d"))
            try:
                # The default format mixes strftime codes (%Y-%m-%d) and braces.
                name = stamp.strftime(name)
            except ValueError:  # pragma: no cover - exotic custom format
                pass
        else:
            name = f"{slug}.md"
        if not name.lower().endswith(".md"):
            name += ".md"
        folder = (folder or "").strip("/")
        candidate = f"{folder}/{name}" if folder else name
        counter = 2
        stem = name[:-3]
        while (self.root / candidate).exists() or self.exists(candidate):
            candidate = f"{folder}/{stem}-{counter}.md" if folder else f"{stem}-{counter}.md"
            counter += 1
        return candidate

    def create(
        self,
        title: Optional[str] = None,
        content: str = "",
        tags: Sequence[str] = (),
        folder: str = "",
        template: Optional[str] = None,
        when: Optional[float] = None,
        *,
        add_heading: Optional[bool] = None,
        index: bool = True,
    ) -> Note:
        """Create a note. Returns the :class:`Note` (content included)."""
        from tuinotes.templates import render_template  # local import: avoids a cycle

        self.ensure_dirs()
        when = when if when is not None else time.time()
        body = content
        if template:
            body = render_template(
                template,
                title=title or datetime.fromtimestamp(when).strftime("%Y-%m-%d"),
                config=self.config,
                tags=tags,
                when=when,
            )
        elif title is None:
            title = md.extract_title(body, fallback="")
        if not title:
            title = datetime.fromtimestamp(when).strftime(self.config.daily.title_format)

        if add_heading is None:
            # Inject a heading when the user named the note but the content does
            # not already carry that title; leave hand-written content alone.
            derived = md.extract_title(body, fallback="")
            add_heading = (
                not template
                and bool(title)
                and derived.lower().strip() != title.lower().strip()
            )
        heading = f"# {title}\n\n" if add_heading else ""

        if tags:
            tag_line = " ".join(tag if tag.startswith("#") else f"#{tag}" for tag in tags)
            existing = {t.lower() for t in md.extract_tags(body)}
            missing = [token for token in tag_line.split() if token[1:].lower() not in existing]
            if missing:
                body = (body.rstrip() + "\n\n" if body.strip() else "") + " ".join(missing) + "\n"

        text = heading + body
        if not text.endswith("\n"):
            text += "\n"

        path = self.new_path(title, folder=folder, when=when)
        target = self.root / path
        self.atomic_write(target, text)
        os.utime(target, (when, when))
        ref = self.index_path(path) if index else self._ref_from_file(path, when)
        self._cache.clear()
        self._fire("created", ref)
        return Note(ref=ref, content=text)

    def _ref_from_file(self, path: str, when: float) -> NoteRef:
        target = self.root / path
        text = target.read_text(encoding="utf-8", errors="replace")
        return NoteRef(
            path=path,
            title=md.extract_title(text) or Path(path).stem,
            preview=md.extract_preview(text, self.config.list.max_snippet),
            created=when,
            modified=when,
            word_count=md.count_words(text),
            char_count=md.count_chars(text),
            size=target.stat().st_size,
            tags=tuple(md.extract_tags(text)),
            links=tuple(md.extract_links(text)),
        )

    def index_path(self, path: str) -> NoteRef:
        """(Re)index a single note and return its fresh metadata."""
        with self._lock:
            conn = self.connection
            ref = self._index_file(self.root / path, conn)
            conn.commit()
            self._cache.clear()
            return ref

    def update(
        self,
        note: Note | NoteRef | str,
        content: Optional[str] = None,
        *,
        index: bool = True,
        event: str = "updated",
    ) -> Note:
        """Write new content for an existing note."""
        ref = self._coerce_ref(note)
        target = self.root / ref.path
        if not target.parent.is_dir():
            raise StorageError(f"missing folder for {ref.path}")
        if content is None:
            content = self.read_content(ref.path)
        if ref.encrypted:
            from tuinotes import encryption

            encryption.encrypt_text(content, target, self.config.encryption)
        else:
            if not content.endswith("\n"):
                content += "\n"
            self.atomic_write(target, content)
        if index:
            ref = self.index_path(ref.path)
        self._cache.clear()
        self._fire(event, ref)
        return Note(ref=ref, content=content)

    def _coerce_ref(self, note: Note | NoteRef | str) -> NoteRef:
        if isinstance(note, Note):
            return note.ref
        if isinstance(note, NoteRef):
            return note
        return self.resolve(note)

    def rename(self, note: Note | NoteRef | str, new_title: str, *, update_links: bool = True) -> Note:
        """Rename a note's file (keeping its date prefix) and fix inbound links."""
        ref = self._coerce_ref(note)
        old_title = ref.title
        slug = md.slugify(new_title)
        if not slug:
            raise StorageError("invalid title")
        match = re.match(r"^(\d{4}-\d{2}-\d{2})-", ref.name)
        prefix = f"{match.group(1)}-" if match and self.config.filename_date_prefix else ""
        suffix = ".md.gpg" if ref.encrypted else ".md"
        folder = ref.folder
        new_name = f"{prefix}{slug}{suffix}"
        new_path = f"{folder}/{new_name}" if folder else new_name
        counter = 2
        while new_path != ref.path and ((self.root / new_path).exists()):
            new_path = (
                f"{folder}/{prefix}{slug}-{counter}{suffix}" if folder else f"{prefix}{slug}-{counter}{suffix}"
            )
            counter += 1
        if new_path != ref.path:
            os.replace(self.root / ref.path, self.root / new_path)
            if not ref.encrypted:
                target = self.root / new_path
                try:
                    text = target.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    text = ""
                updated = md.rename_heading(text, old_title, new_title)
                if updated != text:
                    self.atomic_write(target, updated)
            with self._lock:
                conn = self.connection
                created = self._previous_created(ref.path, conn)
                self._delete_rows(ref.path, conn)
                conn.commit()
            ref = self.index_path(new_path)
            if created:
                with self._lock:
                    self.connection.execute(
                        "UPDATE notes SET created = ? WHERE path = ?", (created, ref.path)
                    )
                    self.connection.commit()
                ref = self._ref_for(ref.path)
        if update_links and old_title:
            self.update_links(old_title, new_title)
        self._cache.clear()
        self._fire("renamed", ref)
        return Note(ref=ref, content=self.read_content(ref.path, decrypt=False))

    def update_links(self, old_title: str, new_title: str) -> int:
        """Rewrite ``[[old title]]`` references after a rename."""
        changed = 0
        pattern = re.compile(
            r"\[\[" + re.escape(old_title) + r"(\|[^\[\]]*)?\]\]", re.IGNORECASE
        )
        for ref in self.all_refs():
            if ref.encrypted:
                continue
            text = self.read_content(ref.path, decrypt=False)
            if "[[" not in text:
                continue
            replaced = pattern.sub(lambda m: f"[[{new_title}{m.group(1) or ''}]]", text)
            if replaced != text:
                self.atomic_write(self.root / ref.path, replaced)
                self.index_path(ref.path)
                changed += 1
        return changed

    def add_tags(self, note: Note | NoteRef | str, tags: Sequence[str]) -> Note:
        ref = self._coerce_ref(note)
        text = self.read_content(ref.path, decrypt=not ref.encrypted)
        existing = {t.lower() for t in ref.tags}
        missing = [t.lstrip("#") for t in tags if t.lstrip("#").lower() not in existing]
        if missing:
            line = " ".join(f"#{tag}" for tag in missing)
            text = (text.rstrip() + "\n\n" if text.strip() else "") + line + "\n"
            return self.update(ref, text)
        return Note(ref=ref, content=text)

    def remove_tags(self, note: Note | NoteRef | str, tags: Sequence[str]) -> Note:
        ref = self._coerce_ref(note)
        text = self.read_content(ref.path, decrypt=not ref.encrypted)
        drop = {t.lstrip("#").lower() for t in tags}

        def _sub(match: re.Match[str]) -> str:
            return "" if match.group(1).lower() in drop else match.group(0)

        replaced = re.sub(r"(?<![\w`])#([\w][\w\-.]{0,63})", _sub, text)
        replaced = re.sub(r"[ \t]{2,}", " ", replaced)
        replaced = re.sub(r"\n{3,}", "\n\n", replaced).strip() + "\n"
        return self.update(ref, replaced)

    # ------------------------------------------------------------------- trash
    def delete(self, note: Note | NoteRef | str, *, permanent: bool = False) -> str:
        """Move a note to ``.trash`` (or delete it for good). Returns the trash path."""
        ref = self._coerce_ref(note)
        source = self.root / ref.path
        if not source.is_file():
            raise NoteNotFound(ref.path)
        if permanent:
            source.unlink()
            with self._lock:
                self._delete_rows(ref.path)
                self.connection.commit()
            self._cache.clear()
            self._fire("deleted", ref)
            return ""
        self.trash_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        digest = hashlib.sha1(ref.path.encode("utf-8")).hexdigest()[:6]
        trash_name = f"{stamp}-{digest}-{ref.name}"
        target = self.trash_dir / trash_name
        shutil.move(str(source), str(target))
        with self._lock:
            conn = self.connection
            self._delete_rows(ref.path, conn)
            conn.execute(
                "INSERT OR REPLACE INTO trash(path, original_path, deleted, title) VALUES (?, ?, ?, ?)",
                (trash_name, ref.path, time.time(), ref.title),
            )
            conn.commit()
        self._cache.clear()
        self._fire("deleted", ref)
        return trash_name

    def list_trash(self) -> List[TrashEntry]:
        with self._lock:
            rows = self.connection.execute(
                "SELECT path, original_path, deleted, title FROM trash ORDER BY deleted DESC"
            ).fetchall()
        entries = [
            TrashEntry(
                path=row["path"],
                original_path=row["original_path"],
                deleted=float(row["deleted"] or 0.0),
                title=row["title"] or DEFAULT_TITLE,
            )
            for row in rows
        ]
        # Drop rows whose file vanished (e.g. synced deletions).
        live = []
        for entry in entries:
            if (self.trash_dir / entry.path).is_file():
                live.append(entry)
        return live

    def restore(self, trash_path: str) -> NoteRef:
        with self._lock:
            row = self.connection.execute(
                "SELECT path, original_path, title FROM trash WHERE path = ?", (trash_path,)
            ).fetchone()
        if row is None:
            raise NoteNotFound(trash_path)
        source = self.trash_dir / row["path"]
        if not source.is_file():
            raise NoteNotFound(trash_path)
        original = row["original_path"]
        target = self.root / original
        target.parent.mkdir(parents=True, exist_ok=True)
        counter = 2
        while target.exists():
            target = self.root / f"{Path(original).stem}-{counter}{Path(original).suffix}"
            counter += 1
        shutil.move(str(source), str(target))
        with self._lock:
            self.connection.execute("DELETE FROM trash WHERE path = ?", (trash_path,))
            self.connection.commit()
        ref = self.index_path(self._rel(target))
        self._cache.clear()
        self._fire("restored", ref)
        return ref

    def purge_trash(self, days: Optional[int] = None) -> int:
        """Delete trashed notes older than the retention window."""
        days = self.config.trash.retention_days if days is None else days
        cutoff = time.time() - days * 86400
        purged = 0
        for entry in self.list_trash():
            if entry.deleted <= cutoff:
                try:
                    (self.trash_dir / entry.path).unlink()
                except OSError:
                    continue
                with self._lock:
                    self.connection.execute("DELETE FROM trash WHERE path = ?", (entry.path,))
                    self.connection.commit()
                purged += 1
        return purged

    # ------------------------------------------------------------------ search
    def search(
        self,
        query: str,
        tags: Sequence[str] = (),
        limit: int = 50,
        *,
        content: bool = True,
        sync: bool = True,
    ) -> List[SearchResult]:
        """Full-text + fuzzy search across titles, tags and bodies."""
        if sync:
            self.sync()
        parsed = parse_query(query)
        all_tags = tuple(tags) + parsed.tags
        refs = self.all_refs(sync=False)
        if parsed.path_filter:
            prefix = parsed.path_filter.strip("/") + "/"
            refs = [ref for ref in refs if ref.path.startswith(prefix)]
        if all_tags or parsed.negated_tags:
            refs = [
                ref for ref in refs if matches_tags(ref, all_tags, parsed.negated_tags)
            ]

        results: Dict[str, SearchResult] = {}
        if parsed.text and content:
            for result in self._fts_search(parsed, refs):
                results[result.path] = result
        if parsed.text and self.config.list.fuzzy:
            for result in self._fuzzy_search(parsed, refs, exclude=set(results)):
                results[result.path] = result
        if not parsed.text:
            for ref in refs:
                results[ref.path] = SearchResult(ref=ref, score=1.0, snippet=ref.preview,
                                                 matched_tags=tuple(all_tags))
        ranked = rank(results.values())
        return ranked[:limit] if limit else ranked

    def _fts_search(self, parsed: ParsedQuery, refs: List[NoteRef]) -> List[SearchResult]:
        if not self._has_fts:
            return self._like_search(parsed, refs)
        terms = [token for token in parsed.text.split() if token]
        if not terms:
            return []
        match = " AND ".join(f'"{term.strip(chr(34))}"*' for term in terms)
        sql = (
            "SELECT path, bm25(notes_fts) AS score, "
            "snippet(notes_fts, 2, '\u0001', '\u0002', ' … ', 18) AS snip "
            "FROM notes_fts WHERE notes_fts MATCH ? ORDER BY bm25(notes_fts) LIMIT 200"
        )
        try:
            with self._lock:
                rows = self.connection.execute(sql, (match,)).fetchall()
        except sqlite3.OperationalError:
            return self._like_search(parsed, refs)
        by_path = {ref.path: ref for ref in refs}
        out: List[SearchResult] = []
        for row in rows:
            ref = by_path.get(row["path"])
            if ref is None:
                continue
            snippet = (row["snip"] or ref.preview).replace("\x01", "[").replace("\x02", "]")
            score = 1.0 / (1.0 + max(0.0, float(row["score"] or 0.0)))
            title_bonus = 0.0
            for term in terms:
                if term.lower() in ref.title.lower():
                    title_bonus = max(title_bonus, 0.35)
            out.append(
                SearchResult(
                    ref=ref,
                    score=min(1.6, score + title_bonus),
                    snippet=snippet.strip(),
                    matched_tags=ref.tags,
                )
            )
        return out

    def _like_search(self, parsed: ParsedQuery, refs: List[NoteRef]) -> List[SearchResult]:
        """Fallback when FTS5 is unavailable (or the query cannot be parsed)."""
        out: List[SearchResult] = []
        needle = parsed.text.lower()
        for ref in refs:
            haystack = f"{ref.title} {ref.preview} {' '.join(ref.tags)}".lower()
            if needle and needle not in haystack:
                continue
            score = 0.9 if needle in ref.title.lower() else 0.6
            out.append(
                SearchResult(
                    ref=ref,
                    score=score,
                    snippet=snippet_around(ref.preview, parsed.text, self.config.list.max_snippet),
                    matched_tags=ref.tags,
                )
            )
        return out

    def _fuzzy_search(
        self, parsed: ParsedQuery, refs: List[NoteRef], exclude: set
    ) -> List[SearchResult]:
        """Subsequence matches for typos / abbreviations, capped for big vaults."""
        needle = parsed.text.strip()
        if not needle:
            return []
        primary = needle.split()[0]
        out: List[SearchResult] = []
        for ref in refs[:5000]:
            if ref.path in exclude:
                continue
            score, field_name = best_field_score(primary, ref)
            if score is None or score <= 0:
                continue
            if field_name == "title":
                score *= 1.0
            out.append(
                SearchResult(
                    ref=ref,
                    score=score * 0.9,
                    snippet=snippet_around(ref.preview, needle, self.config.list.max_snippet),
                    matched_tags=ref.tags,
                )
            )
        return out

    # ------------------------------------------------------------ organisation
    def tag_counts(self) -> List[Tuple[str, int]]:
        from tuinotes.models import unique_tags

        return unique_tags(self.all_refs())

    def folders(self) -> List[Tuple[str, int]]:
        counts: Dict[str, int] = {}
        for ref in self.all_refs():
            counts[ref.folder or "/"] = counts.get(ref.folder or "/", 0) + 1
        return sorted(counts.items(), key=lambda item: item[0])

    def backlinks(self, note: Note | NoteRef | str) -> List[NoteRef]:
        """Notes that reference ``note`` via ``[[wikilink]]``."""
        ref = self._coerce_ref(note)
        keys = {ref.title.lower(), ref.stem.lower()}
        out: List[NoteRef] = []
        for candidate in self.all_refs():
            if candidate.path == ref.path or not candidate.links:
                continue
            if any(link.lower() in keys for link in candidate.links):
                out.append(candidate)
        return out

    def outgoing(self, note: Note | NoteRef | str) -> List[Tuple[str, Optional[NoteRef]]]:
        """``[[links]]`` in a note paired with the note they resolve to (or None)."""
        ref = self._coerce_ref(note)
        by_title: Dict[str, NoteRef] = {}
        for candidate in self.all_refs():
            by_title.setdefault(candidate.title.lower(), candidate)
            by_title.setdefault(candidate.stem.lower(), candidate)
        return [(link, by_title.get(link.lower())) for link in ref.links]

    def daily_path(self, day: Optional[date_cls] = None) -> str:
        day = day or datetime.now().date()
        stamp = day.strftime(self.config.daily.title_format)
        return f"{stamp}.md"

    def daily_note(self, day: Optional[date_cls] = None, template: Optional[str] = None) -> Note:
        """Return today's note, creating it from a template when missing."""
        self.sync()
        day = day or datetime.now().date()
        path = self.daily_path(day)
        if self.exists(path):
            ref = self._ref_for(path)
            return Note(ref=ref, content=self.read_content(path, decrypt=False))
        from tuinotes.templates import render_template

        when = datetime(day.year, day.month, day.day, 8, 0).timestamp()
        title = day.strftime(self.config.daily.title_format)
        text = render_template(
            template or self.config.daily.template,
            title=title,
            config=self.config,
            when=when,
        )
        if not text.strip():
            text = f"# {title}\n\n"
        if not text.endswith("\n"):
            text += "\n"
        self.ensure_dirs()
        self.atomic_write(self.root / path, text)
        os.utime(self.root / path, (when, when))
        ref = self.index_path(path)
        self._cache.clear()
        self._fire("created", ref)
        return Note(ref=ref, content=text)

    def import_file(self, source: Path, *, folder: str = "") -> Note:
        """Copy an external Markdown file into the vault and index it."""
        source = Path(source)
        if not source.is_file():
            raise StorageError(f"{source} is not a file")
        text = source.read_text(encoding="utf-8", errors="replace")
        title = md.extract_title(text, fallback=source.stem)
        path = self.new_path(title, folder=folder)
        self.atomic_write(self.root / path, text)
        ref = self.index_path(path)
        self._cache.clear()
        self._fire("created", ref)
        return Note(ref=ref, content=text)

    # ------------------------------------------------------------------- stats
    def stats(self) -> Dict[str, Any]:
        refs = self.all_refs()
        total_words = sum(ref.word_count for ref in refs)
        total_size = sum(ref.size for ref in refs)
        tags = {tag for ref in refs for tag in ref.tags}
        db_size = self.db_path.stat().st_size if self.db_path.is_file() else 0
        return {
            "vault": str(self.root),
            "notes": len(refs),
            "words": total_words,
            "bytes": total_size,
            "tags": len(tags),
            "encrypted": sum(1 for ref in refs if ref.encrypted),
            "linked": sum(1 for ref in refs if ref.links),
            "trash": len(self.list_trash()),
            "index_bytes": db_size,
            "fts": self._has_fts,
        }
