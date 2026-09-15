"""Markdown parsing helpers."""

from __future__ import annotations

from tuinotes import markdown_utils as md


def test_title_from_atx_heading():
    assert md.extract_title("# Meeting notes\n\nbody") == "Meeting notes"


def test_title_from_first_line_and_strips_tags():
    assert md.extract_title("buy milk and eggs #shopping\n") == "buy milk and eggs"


def test_title_from_setext_heading():
    assert md.extract_title("Journal\n=======\n\ntext") == "Journal"


def test_title_fallback():
    assert md.extract_title("", fallback="Untitled") == "Untitled"


def test_title_skips_front_matter_rule():
    assert md.extract_title("---\nReal title here\n") == "Real title here"


def test_preview_strips_markup_and_truncates():
    text = "# Title\n\nSome **bold** [link](http://x) body text here\n"
    preview = md.extract_preview(text, limit=20)
    assert preview.endswith("…")
    assert "**" not in preview and "http" not in preview


def test_preview_skips_headings_and_fences():
    text = "# Heading\n\n```\ncode only\n```\n\nActual preview line\n"
    assert md.extract_preview(text) == "Actual preview line"


def test_tags_are_extracted_and_deduplicated():
    text = "intro #rust #Rust #async\ntail"
    assert md.extract_tags(text) == ["rust", "async"]


def test_tags_ignore_code_blocks():
    text = "```\n#not-a-tag\n```\n\nreal #tag\n"
    assert md.extract_tags(text) == ["tag"]


def test_heading_can_carry_a_tag():
    assert md.extract_tags("# Title #project\n") == ["project"]


def test_wikilinks_with_alias():
    text = "see [[Rust async notes]] and [[Tokio notes|tokio]] and [[Rust async notes]]"
    assert md.extract_links(text) == ["Rust async notes", "Tokio notes"]


def test_word_count_ignores_markup():
    assert md.count_words("# Title\n\nthree little words\n") == 4
    assert md.count_words("**bold** and `code`") == 3


def test_slugify_ascii_and_unicode():
    assert md.slugify("Hello, World!") == "Hello-World"
    assert md.slugify("日本語ノート") == "日本語ノート"
    assert md.slugify("   ") == "note"


def test_code_fence_stripping_keeps_line_numbers():
    text = "one\n```\ntwo\n```\nthree"
    stripped = md.strip_code_fences(text)
    assert stripped.splitlines() == ["one", "", "", "", "three"]


def test_find_occurrences_and_location():
    text = "alpha beta alpha"
    assert md.find_occurrences(text, "alpha") == [0, 11]
    assert md.location_of_offset(text, 11) == (0, 11)
    assert md.location_of_offset("a\nb", 2) == (1, 0)
