"""Vim-style ``:command`` parsing."""

from __future__ import annotations

from tuinotes.commands import (
    COMMANDS,
    completions,
    help_lines,
    parse_command,
    suggest,
)


def test_simple_command():
    parsed = parse_command(":w")
    assert parsed.ok and parsed.name == "w" and parsed.args == ()


def test_command_without_colon():
    assert parse_command("q").name == "q"


def test_arguments_are_shell_split():
    parsed = parse_command(":export pdf \"My Notes.pdf\"")
    assert parsed.name == "export"
    assert parsed.args == ("pdf", "My Notes.pdf")


def test_aliases_resolve_to_canonical_names():
    assert parse_command(":quit").name == "q"
    assert parse_command(":x").name == "wq"
    assert parse_command(":new idea").name == "n"
    assert parse_command(":rm note").name == "d"


def test_unknown_command_reports_and_suggests():
    parsed = parse_command(":wrtie")
    assert not parsed.ok
    assert "unknown command" in parsed.error
    assert "w" in parsed.error  # prefix suggestion


def test_empty_command_is_an_error():
    assert not parse_command(":").ok
    assert not parse_command("   ").ok


def test_suggest_prefix_first():
    assert suggest("ta")[0] in {"tag", "tags", "templates"}


def test_completions_include_help_text():
    matches = completions(":exp")
    assert matches and matches[0][0] == "export"
    assert matches[0][1]


def test_help_lines_cover_every_documented_command():
    lines = help_lines()
    assert len(lines) == len(COMMANDS)
    assert any(line.startswith(":w ") or line.startswith(":w —") for line in lines)


def test_every_command_has_metadata():
    for name, spec in COMMANDS.items():
        assert "help" in spec and "scope" in spec, name
        assert spec["scope"] in {"all", "editor", "list"}, name
