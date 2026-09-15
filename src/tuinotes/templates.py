"""Note templates (meeting notes, daily journal, research, ...).

Built-in templates ship with the package; user templates live in
``<vault>/.templates/*.md`` (or ``templates_dir`` from the config) and win over
built-ins with the same name.  Substitution is a tiny ``{{key}}`` renderer, so
templates stay valid Markdown and are easy to share.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

from tuinotes.config import Config

BUILTIN_TEMPLATES: Dict[str, str] = {
    "daily": """# {{date}}

## Plan
- [ ]

## Notes

## Log
- {{time}} —

## Grateful for

#journal #daily
""",
    "meeting": """# Meeting: {{title}}

**Date:** {{date}} {{time}}
**Attendees:**
**Location:**

## Agenda
1.

## Decisions
-

## Action items
- [ ] @who — what — by when

## Notes

#meeting
""",
    "idea": """# {{title}}

**When:** {{date}} {{time}}

## The idea

## Why it matters

## Next step
- [ ]

#idea
""",
    "research": """# {{title}}

**Source:**
**Author:**
**Read:** {{date}}

## Summary

## Key points
-

## Quotes
>

## Questions
-

## Related
- [[]]

#research
""",
    "todo": """# {{title}}

## Today
- [ ]

## Soon
- [ ]

## Someday
- [ ]

#todo
""",
    "journal": """# Journal — {{date}}

**Mood:**

## What happened

## What I learned

## Tomorrow

#journal
""",
    "weekly": """# Weekly review — {{week}}

## Wins

## Stuck on

## Next week
- [ ]

## Review
- Energy:
- Focus:

#review #weekly
""",
    "project": """# Project: {{title}}

**Status:** active
**Started:** {{date}}

## Goal

## Milestones
- [ ]

## Log
- {{date}} —

## Links
- [[]]

#project
""",
    "blank": "",
}

TEMPLATE_DESCRIPTIONS: Dict[str, str] = {
    "daily": "Daily journal with plan, notes and log",
    "meeting": "Meeting notes with agenda, decisions and actions",
    "idea": "Quick idea capture",
    "research": "Article / paper research notes",
    "todo": "Task list (today / soon / someday)",
    "journal": "Long-form journal entry",
    "weekly": "Weekly review",
    "project": "Project page with milestones and log",
    "blank": "Empty note",
}


class TemplateNotFound(KeyError):
    """Raised when a template name does not exist."""


def template_dirs(config: Config) -> List[Path]:
    """Directories scanned for user templates (highest priority first)."""
    return [config.templates_dir_path]


def user_templates(config: Config) -> List[str]:
    names: List[str] = []
    for directory in template_dirs(config):
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.md")):
            names.append(path.stem)
    return names


def available_templates(config: Config) -> List[str]:
    return sorted(set(BUILTIN_TEMPLATES) | set(user_templates(config)))


def describe(name: str, config: Optional[Config] = None) -> str:
    if config is not None and name in user_templates(config):
        return "user template"
    return TEMPLATE_DESCRIPTIONS.get(name, "built-in template")


def load_template(name: str, config: Config) -> str:
    """Return the raw template text for ``name``."""
    for directory in template_dirs(config):
        candidate = directory / f"{name}.md"
        if candidate.is_file():
            return candidate.read_text(encoding="utf-8", errors="replace")
    if name in BUILTIN_TEMPLATES:
        return BUILTIN_TEMPLATES[name]
    suggestions = ", ".join(available_templates(config))
    raise TemplateNotFound(f"unknown template {name!r} (available: {suggestions})")


def render_template(
    name: str,
    title: str = "",
    config: Optional[Config] = None,
    tags: Sequence[str] = (),
    when: Optional[float] = None,
    extra: Optional[Dict[str, str]] = None,
) -> str:
    """Render a template with ``{{date}}``-style placeholders filled in."""
    from tuinotes.config import load_config

    config = config or load_config()
    moment = datetime.fromtimestamp(when) if when else datetime.now()
    context: Dict[str, str] = {
        "title": title or moment.strftime("%Y-%m-%d"),
        "date": moment.strftime("%Y-%m-%d"),
        "long_date": moment.strftime("%A, %B %d %Y"),
        "time": moment.strftime("%H:%M"),
        "datetime": moment.strftime("%Y-%m-%d %H:%M"),
        "year": moment.strftime("%Y"),
        "month": moment.strftime("%m"),
        "day": moment.strftime("%d"),
        "weekday": moment.strftime("%A"),
        "week": f"{moment.strftime('%Y')}-W{moment.isocalendar()[1]:02d}",
        "tags": " ".join(
            tag if tag.startswith("#") else f"#{tag}" for tag in (tags or [])
        ).strip(),
    }
    if extra:
        context.update(extra)
    text = load_template(name, config)
    for key, value in context.items():
        text = text.replace("{{" + key + "}}", value)
        text = text.replace("{{ " + key + " }}", value)
    return text


def write_user_template(name: str, body: str, config: Config) -> Path:
    """Save a template into the vault so it syncs with your notes."""
    directory = config.templates_dir_path
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{name}.md"
    target.write_text(body, encoding="utf-8")
    return target


def import_templates(config: Config, overwrite: bool = False) -> List[str]:
    """Copy the built-in templates into the vault for easy editing."""
    written: List[str] = []
    for name, body in BUILTIN_TEMPLATES.items():
        if name == "blank":
            continue
        target = config.templates_dir_path / f"{name}.md"
        if target.exists() and not overwrite:
            continue
        written.append(str(write_user_template(name, body, config)))
    return written


def iter_builtin_templates() -> Iterable[str]:
    return iter(BUILTIN_TEMPLATES)
