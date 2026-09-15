"""Query parsing, fuzzy scoring and highlighting."""

from __future__ import annotations

from tuinotes.models import NoteRef
from tuinotes.search import (
    SearchResult,
    best_field_score,
    fuzzy_score,
    highlight,
    matches_tags,
    parse_query,
    rank,
    snippet_around,
)


def ref(title: str, preview: str = "", tags=()) -> NoteRef:
    return NoteRef(path=f"{title.lower().replace(' ', '-')}.md", title=title, preview=preview, tags=tuple(tags))


def test_parse_query_tags_and_negation():
    parsed = parse_query("#rust -#wip rust async")
    assert parsed.tags == ("rust",)
    assert parsed.negated_tags == ("wip",)
    assert parsed.text == "rust async"


def test_parse_query_folder_title_and_phrase():
    parsed = parse_query('in:work title:meeting "quarterly review"')
    assert parsed.path_filter == "work"
    assert parsed.title_only is True
    assert parsed.phrases == ("quarterly review",)
    assert "quarterly review" in parsed.text


def test_parse_query_empty():
    assert parse_query("").is_empty
    assert parse_query("   ").is_empty


def test_fuzzy_direct_match_beats_subsequence():
    direct = fuzzy_score("rust", "rust-notes")
    subsequence = fuzzy_score("rn", "rust-notes")
    assert direct is not None and subsequence is not None
    assert direct > subsequence
    assert fuzzy_score("xyz", "rust-notes") is None
    assert fuzzy_score("", "anything") is None


def test_fuzzy_prefers_contiguous_word_initial_matches():
    # "ru" starts a word and is contiguous in "rust-notes"; scattered elsewhere.
    assert fuzzy_score("ru", "rust-notes") > fuzzy_score("ru", "curry-sauce")


def test_fuzzy_finds_literal_substrings_anywhere():
    assert fuzzy_score("rn", "learning-notes") is not None


def test_best_field_score_picks_the_strongest_field():
    score, field = best_field_score("rust", ref("Rust async", tags=["python"]))
    assert field == "title"
    score, field = best_field_score("py", ref("Rust async", tags=["python"]))
    assert field == "tag"


def test_highlight_marks_every_occurrence():
    text = highlight("Tokio and tokio again", ["tokio"])
    spans = [(span.start, span.end) for span in text.spans]
    assert (0, 5) in spans and (10, 15) in spans


def test_highlight_merges_overlapping_needles():
    text = highlight("abcdef", ["abc", "bcd"])
    assert len(text.spans) == 1
    assert (text.spans[0].start, text.spans[0].end) == (0, 4)


def test_snippet_is_centred_on_the_hit():
    body = "word " * 60 + "needle" + " word" * 60
    snippet = snippet_around(body, "needle", width=40)
    assert "needle" in snippet
    assert len(snippet) <= 44
    assert snippet.startswith("…")


def test_matches_tags_case_insensitive():
    note = ref("x", tags=["Rust", "Async"])
    assert matches_tags(note, ["rust"])
    assert not matches_tags(note, ["rust"], ["async"])
    assert matches_tags(note, [], ["python"])


def test_rank_sorts_by_score_then_recency():
    a = SearchResult(ref=NoteRef(path="a.md", title="a", modified=1.0), score=0.5)
    b = SearchResult(ref=NoteRef(path="b.md", title="b", modified=2.0), score=0.5)
    c = SearchResult(ref=NoteRef(path="c.md", title="c", modified=3.0), score=0.9)
    assert [r.path for r in rank([a, b, c])] == ["c.md", "b.md", "a.md"]
