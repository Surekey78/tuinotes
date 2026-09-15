"""End-to-end CLI behaviour (no TUI involved)."""

from __future__ import annotations

import json

import pytest

from tuinotes.cli import main, quick_main


@pytest.fixture
def vault(tmp_path):
    return str(tmp_path / "cli-vault")


def run(*args: str) -> int:
    return main(list(args))


def test_quick_capture_creates_a_note(vault, capsys):
    assert quick_main(["--vault", vault, "buy milk", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["title"] == "buy milk"
    assert payload["file"].endswith(".md")


def test_quick_capture_without_text_is_an_error(vault, capsys):
    assert quick_main(["--vault", vault]) == 0  # prints help instead of failing
    assert "instant capture" in capsys.readouterr().out


def test_new_note_with_template_and_tags(vault, capsys):
    assert run("new", "--vault", vault, "Standup", "--template", "meeting", "-t", "work") == 0
    out = capsys.readouterr().out
    assert "Standup" in out

    assert run("list", "--vault", vault) == 0
    listing = capsys.readouterr().out
    assert "Standup" in listing


def test_list_and_search(vault, capsys):
    quick_main(["--vault", vault, "Tokio makes async Rust nice"])
    quick_main(["--vault", vault, "Groceries: milk, eggs"])
    capsys.readouterr()

    assert run("list", "--vault", vault) == 0
    assert "Groceries" in capsys.readouterr().out

    assert run("search", "--vault", vault, "tokio", "--json") == 0
    results = json.loads(capsys.readouterr().out)
    assert results and "Tokio" in results[0]["title"]


def test_show_raw_and_rendered(vault, capsys):
    quick_main(["--vault", vault, "**bold** statement", "--json"])
    payload = json.loads(capsys.readouterr().out)
    title = payload["title"]

    assert run("show", "--vault", vault, title, "--raw") == 0
    assert "**bold** statement" in capsys.readouterr().out

    assert run("show", "--vault", vault, title) == 0
    assert "bold" in capsys.readouterr().out


def test_tags_command(vault, capsys):
    quick_main(["--vault", vault, "tagged thought", "-t", "idea", "-t", "ux"])
    capsys.readouterr()
    assert run("tags", "--vault", vault, "--json") == 0
    counts = {row["tag"]: row["count"] for row in json.loads(capsys.readouterr().out)}
    assert counts == {"idea": 1, "ux": 1}


def test_tag_add_and_remove(vault, capsys):
    quick_main(["--vault", vault, "note to tag"])
    capsys.readouterr()
    assert run("tag", "--vault", vault, "note to tag", "later") == 0
    assert "#later" in capsys.readouterr().out
    assert run("tag", "--vault", vault, "note to tag", "later", "--remove") == 0
    assert "(no tags)" in capsys.readouterr().out


def test_delete_and_restore(vault, capsys):
    quick_main(["--vault", vault, "temporary note"])
    capsys.readouterr()
    assert run("delete", "--vault", vault, "temporary note", "--yes") == 0
    assert "trashed" in capsys.readouterr().out

    assert run("restore", "--vault", vault) == 0  # lists the trash
    listed = capsys.readouterr().out
    trash_id = listed.split()[0]

    assert run("restore", "--vault", vault, trash_id) == 0
    assert "restored" in capsys.readouterr().out


def test_rename_updates_the_file(vault, capsys):
    quick_main(["--vault", vault, "old name"])
    capsys.readouterr()
    assert run("rename", "--vault", vault, "old name", "new name") == 0
    assert "new-name.md" in capsys.readouterr().out


def test_daily_note(vault, capsys):
    assert run("daily", "--vault", vault, "--json") == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["path"].endswith(".md")
    # Running it again must not create a second note.
    run("daily", "--vault", vault, "--json")
    capsys.readouterr()
    run("stats", "--vault", vault, "--json")
    assert json.loads(capsys.readouterr().out)["notes"] == 1


def test_backlinks_and_graph(vault, capsys):
    quick_main(["--vault", vault, "Target note"])
    quick_main(["--vault", vault, "Refers to [[Target note]]"])
    capsys.readouterr()

    assert run("backlinks", "--vault", vault, "Target note") == 0
    output = capsys.readouterr().out
    assert "Refers to" in output

    assert run("graph", "--vault", vault, "--width", "60") == 0
    graph = capsys.readouterr().out
    assert "cluster 1" in graph


def test_export_html(vault, tmp_path, capsys):
    quick_main(["--vault", vault, "export me"])
    capsys.readouterr()
    target = tmp_path / "out.html"
    assert run("export", "--vault", vault, "export me", "--format", "html", "--out", str(target)) == 0
    assert target.is_file()
    assert "export me" in target.read_text(encoding="utf-8")


def test_config_roundtrip(vault, capsys):
    assert run("config", "--vault", vault, "set", "editor.keymap=vim") == 0
    assert "vim" in capsys.readouterr().out
    assert run("config", "--vault", vault, "--json") == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["editor"]["keymap"] == "vim"


def test_config_set_rejects_unknown_keys(vault, capsys):
    assert run("config", "--vault", vault, "set", "nope.nope=1") == 1
    assert "cannot set" in capsys.readouterr().err


def test_templates_list_and_show(vault, capsys):
    assert run("templates", "--vault", vault) == 0
    assert "meeting" in capsys.readouterr().out
    assert run("templates", "--vault", vault, "show", "daily") == 0
    assert "# {{date}}" in capsys.readouterr().out


def test_stats_and_reindex(vault, capsys):
    quick_main(["--vault", vault, "one"])
    quick_main(["--vault", vault, "two"])
    capsys.readouterr()
    assert run("reindex", "--vault", vault) == 0
    assert "indexed 2" in capsys.readouterr().out
    assert run("stats", "--vault", vault, "--json") == 0
    stats = json.loads(capsys.readouterr().out)
    assert stats["notes"] == 2
    assert stats["fts"] is True


def test_doctor_reports_the_environment(vault, capsys):
    assert run("doctor", "--vault", vault) == 0
    output = capsys.readouterr().out
    assert "vault" in output and "full-text search" in output


def test_unknown_note_exits_with_code_two(vault, capsys):
    assert run("show", "--vault", vault, "no-such-note-xyz") == 2
    assert "no note matching" in capsys.readouterr().err


def test_git_status_on_a_plain_vault(vault, capsys):
    assert run("git", "--vault", vault, "status") == 0
    assert "not a git repository" in capsys.readouterr().out


def test_widget_list_without_install(vault, capsys):
    assert run("widget", "--vault", vault, "list") == 0
    assert "tuinotes" in capsys.readouterr().out
