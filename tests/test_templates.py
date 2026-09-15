"""Templates: built-ins, user overrides and rendering."""

from __future__ import annotations

import time

import pytest

from tuinotes.templates import (
    BUILTIN_TEMPLATES,
    TemplateNotFound,
    available_templates,
    describe,
    import_templates,
    load_template,
    render_template,
    write_user_template,
)


def test_builtin_templates_exist():
    for name in ("daily", "meeting", "idea", "research", "todo", "journal", "weekly", "project"):
        assert name in BUILTIN_TEMPLATES
        assert describe(name)


def test_placeholders_are_filled(config):
    rendered = render_template("meeting", title="Standup", config=config)
    assert "# Meeting: Standup" in rendered
    assert "{{" not in rendered
    assert time.strftime("%Y-%m-%d") in rendered


def test_daily_template_contains_tags_and_date(config):
    rendered = render_template("daily", config=config)
    assert time.strftime("%Y-%m-%d") in rendered
    assert "#journal" in rendered


def test_weekly_template_uses_iso_week(config):
    from datetime import date

    rendered = render_template("weekly", config=config)
    year, week, _ = date.today().isocalendar()
    assert f"{year}-W{week:02d}" in rendered


def test_user_template_overrides_builtin(config):
    write_user_template("daily", "# my own daily {{date}}\n", config)
    assert "daily" in available_templates(config)
    rendered = render_template("daily", config=config)
    assert rendered.startswith("# my own daily")
    assert describe("daily", config) == "user template"


def test_import_templates_copies_builtins_into_the_vault(config):
    written = import_templates(config)
    assert written
    assert (config.templates_dir_path / "meeting.md").is_file()
    # A second run is a no-op unless forced.
    assert import_templates(config) == []
    assert import_templates(config, overwrite=True)


def test_unknown_template_raises_with_suggestions(config):
    with pytest.raises(TemplateNotFound) as error:
        load_template("nope", config)
    assert "daily" in str(error.value)


def test_render_substitutes_the_tags_placeholder(config):
    write_user_template("tagged", "# {{title}}\n\n{{tags}}\n", config)
    rendered = render_template("tagged", title="Widget", config=config, tags=["idea", "ux"])
    assert rendered.startswith("# Widget")
    assert "#idea #ux" in rendered


def test_render_accepts_extra_context(config):
    rendered = render_template("idea", title="Widget", config=config, extra={"title": "Override"})
    assert rendered.startswith("# Override")
