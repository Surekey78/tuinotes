"""A TextArea that highlights Markdown with or without tree-sitter.

Textual's own highlighting needs the (optional, Python 3.10+) ``textual[syntax]``
extra.  On Termux that extra means compiling tree-sitter, so tuinotes ships a
small regex highlighter that plugs into the same rendering path — headings,
emphasis, code, links, ``#tags`` and ``[[wikilinks]]`` are coloured either way.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

from textual.widgets import TextArea

Span = Tuple[int, int, str]  # (start_byte, end_byte, highlight_name)

FENCE_RE = re.compile(r"^\s{0,3}(```|~~~)")
HEADING_RE = re.compile(r"^(\s{0,3})(#{1,6})(\s+)(.*)$")
HR_RE = re.compile(r"^\s{0,3}(-{3,}|\*{3,}|_{3,})\s*$")
QUOTE_RE = re.compile(r"^(\s{0,3})(>+\s?)(.*)$")
LIST_RE = re.compile(r"^(\s*)([-*+]|\d{1,9}[.)])(\s+)(\[[ xX]\]\s+)?(.*)$")
CODE_RE = re.compile(r"(`+)([^`]|[^`].*?[^`])\1(?!`)")
BOLD_RE = re.compile(r"(\*\*|__)(?=\S)(.+?)(?<=\S)\1")
ITALIC_RE = re.compile(r"(?<![\w*])\*(?=\S)([^*\n]+?)(?<=\S)\*(?![\w*])|(?<![\w_])_(?=\S)([^_\n]+?)(?<=\S)_(?![\w_])")
STRIKE_RE = re.compile(r"(~~)(?=\S)(.+?)(?<=\S)\1")
LINK_RE = re.compile(r"\[([^\]]*)\]\(([^)\s]+)[^)]*\)")
WIKILINK_RE = re.compile(r"(\[\[)([^\[\]]+?)(\]\])")
TAG_RE = re.compile(r"(?<![\w`])#[\w][\w\-.]{0,63}")
TABLE_RE = re.compile(r"\|")


def _has_tree_sitter_markdown() -> bool:
    """True when Textual can do native tree-sitter Markdown highlighting."""
    try:
        from textual._tree_sitter import TREE_SITTER, get_language

        if not TREE_SITTER:
            return False
        return get_language("markdown") is not None
    except Exception:  # pragma: no cover - depends on installed extras
        return False


NATIVE_HIGHLIGHTING = _has_tree_sitter_markdown()


class MarkdownArea(TextArea):
    """Markdown-aware editor widget."""

    def __init__(self, *args, **kwargs) -> None:
        self._native_highlighting: bool = bool(
            kwargs.pop("native_highlighting", NATIVE_HIGHLIGHTING)
        )
        if self._native_highlighting:
            kwargs.setdefault("language", "markdown")
        else:
            kwargs.setdefault("language", None)
        # TextArea builds its highlight map during __init__, so these must exist
        # before super().__init__ runs.
        self._highlight_cache_key: Optional[str] = None
        self._highlight_cache: Dict[int, List[Span]] = {}
        super().__init__(*args, **kwargs)

    # -------------------------------------------------------------------- keys
    async def _on_key(self, event) -> None:  # noqa: D102 - Textual hook
        """Let Escape bubble up to the screen.

        With ``tab_behavior="indent"`` TextArea would otherwise consume Escape
        and hop focus, which breaks both vim's modal Escape and the "Escape goes
        back" behaviour every other screen relies on.
        """
        if event.key == "escape":
            return
        await super()._on_key(event)

    # ------------------------------------------------------------------ render
    def _build_highlight_map(self) -> None:  # noqa: D102 - Textual hook
        """Fill TextArea's highlight map (tree-sitter or our regex fallback)."""
        if self._native_highlighting:
            super()._build_highlight_map()
            return
        try:
            self._line_cache.clear()
        except AttributeError:  # pragma: no cover - Textual internals
            pass
        highlights = self._highlights
        highlights.clear()
        text = self.text
        if self._highlight_cache_key != text:
            self._highlight_cache = _scan(text)
            self._highlight_cache_key = text
        for line_index, spans in self._highlight_cache.items():
            if spans:
                highlights[line_index].extend(spans)

    # ------------------------------------------------------------- convenience
    @property
    def line_count(self) -> int:
        return self.document.line_count

    def line_text(self, index: int) -> str:
        try:
            return self.get_line(index).plain
        except IndexError:
            return ""


def _scan(text: str) -> Dict[int, List[Span]]:
    """Compute per-line highlight spans (UTF-8 byte offsets) for ``text``."""
    out: Dict[int, List[Span]] = {}
    in_fence = False
    fence_token = ""
    for index, line in enumerate(text.split("\n")):
        spans = _line_spans(line, index, in_fence)
        fence = FENCE_RE.match(line)
        if fence:
            token = fence.group(1)
            if not in_fence:
                in_fence, fence_token = True, token
            elif token == fence_token:
                in_fence, fence_token = False, ""
        if spans:
            out[index] = spans
    return out


def _line_spans(line: str, index: int, in_fence: bool) -> List[Span]:
    spans: List[Span] = []
    if in_fence or FENCE_RE.match(line):
        spans.append(_byte_span(line, 0, len(line), "inline_code"))
        return spans
    if not line.strip():
        return spans

    heading = HEADING_RE.match(line)
    if heading:
        marker_start = len(heading.group(1))
        marker_end = marker_start + len(heading.group(2)) + len(heading.group(3))
        spans.append(_byte_span(line, marker_start, marker_end, "heading.marker"))
        spans.append(_byte_span(line, marker_end, len(line), "heading"))
        spans.extend(_inline_spans(line, start=marker_end))
        return spans

    if HR_RE.match(line):
        spans.append(_byte_span(line, 0, len(line), "heading.marker"))
        return spans

    quote = QUOTE_RE.match(line)
    if quote:
        marker_end = len(quote.group(1)) + len(quote.group(2))
        spans.append(_byte_span(line, 0, marker_end, "list.marker"))
        spans.append(_byte_span(line, marker_end, len(line), "string.documentation"))
        spans.extend(_inline_spans(line, start=marker_end))
        return spans

    listing = LIST_RE.match(line)
    if listing:
        marker_start = len(listing.group(1))
        marker_end = marker_start + len(listing.group(2)) + len(listing.group(3))
        spans.append(_byte_span(line, marker_start, marker_end, "list.marker"))
        if listing.group(4):
            box_end = marker_end + len(listing.group(4))
            spans.append(_byte_span(line, marker_end, box_end, "boolean"))
            marker_end = box_end
        spans.extend(_inline_spans(line, start=marker_end))
        return spans

    spans.extend(_inline_spans(line))
    return spans


def _inline_spans(line: str, start: int = 0) -> List[Span]:
    """Inline emphasis, code, links, tags and table pipes."""
    spans: List[Span] = []
    for match in CODE_RE.finditer(line, start):
        spans.append(_byte_span(line, match.start(), match.end(), "inline_code"))
    for match in BOLD_RE.finditer(line, start):
        spans.append(_byte_span(line, match.start(), match.end(), "bold"))
    for match in ITALIC_RE.finditer(line, start):
        spans.append(_byte_span(line, match.start(), match.end(), "italic"))
    for match in STRIKE_RE.finditer(line, start):
        spans.append(_byte_span(line, match.start(), match.end(), "strikethrough"))
    for match in LINK_RE.finditer(line, start):
        spans.append(_byte_span(line, match.start(1), match.end(1), "link.label"))
        spans.append(_byte_span(line, match.start(2), match.end(2), "link.uri"))
    for match in WIKILINK_RE.finditer(line, start):
        spans.append(_byte_span(line, match.start(), match.end(), "type"))
    for match in TAG_RE.finditer(line, start):
        spans.append(_byte_span(line, match.start(), match.end(), "keyword"))
    for match in TABLE_RE.finditer(line, start):
        spans.append(_byte_span(line, match.start(), match.end(), "punctuation.delimiter"))
    return [span for span in spans if span[1] > span[0]]


def _byte_span(line: str, start: int, end: int, name: str) -> Span:
    """Convert codepoint offsets into the UTF-8 byte offsets TextArea expects."""
    start = max(0, min(start, len(line)))
    end = max(start, min(end, len(line)))
    return (len(line[:start].encode("utf-8")), len(line[:end].encode("utf-8")), name)
