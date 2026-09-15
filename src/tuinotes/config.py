"""Configuration handling for tuinotes.

Config resolution order (later wins):

1. built-in defaults (this module),
2. ``~/.config/tuinotes/config.json`` — user-global preferences,
3. ``<notes-dir>/.config.json`` — per-vault preferences (syncs with your notes),
4. environment variables (``TUINOTES_HOME``, ``TUINOTES_THEME``, ...).

The on-disk format is plain JSON, so it round-trips through Syncthing, Git and a
text editor without surprises.  Unknown keys are preserved on save so that
downgrading never destroys settings.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, fields, is_dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

APP_NAME = "tuinotes"
ENV_HOME = "TUINOTES_HOME"
ENV_CONFIG = "TUINOTES_CONFIG"
ENV_THEME = "TUINOTES_THEME"
ENV_EDITOR = "VISUAL"

DEFAULT_NOTES_DIR = "~/notes"
CONFIG_FILENAME = ".config.json"
METADATA_FILENAME = ".metadata.db"
TRASH_DIRNAME = ".trash"
TEMPLATES_DIRNAME = ".templates"

SORT_KEYS = ("modified", "newest", "oldest", "alphabetical")
EDITOR_KEYMAPS = ("normal", "vim", "emacs")


def _empty_list() -> list:
    """Factory that survives the ``list`` field shadowing the builtin."""
    return []


def _expand(path: str | os.PathLike[str]) -> Path:
    """Expand ``~`` and environment variables, and normalise the result."""
    return Path(os.path.expandvars(str(path))).expanduser().resolve()


@dataclass
class EditorConfig:
    """Editor behaviour (the screen you spend most of your time in)."""

    keymap: str = "normal"
    """``normal`` (touch/default keys), ``vim`` (modal hjkl) or ``emacs`` (C-a/C-e/C-k)."""

    line_numbers: bool = True
    soft_wrap: bool = True
    tab_size: int = 4
    autosave: bool = True
    autosave_interval: float = 3.0
    """Seconds of inactivity before an auto-save, per the project spec."""

    spellcheck: bool = False
    show_word_count: bool = True
    highlight_tags: bool = True
    syntax_highlight: bool = True


@dataclass
class ListConfig:
    """Note-list behaviour."""

    sort: str = "modified"
    page_size: int = 100
    """Rows loaded per batch — keeps 1000+ note vaults instant to open."""

    show_preview: bool = True
    show_tags: bool = True
    show_date: bool = True
    fuzzy: bool = True
    case_sensitive: bool = False
    max_snippet: int = 160


@dataclass
class GitConfig:
    """Optional Git sync."""

    enabled: bool = False
    auto_commit: bool = True
    remote: str = "origin"
    branch: str = ""
    """Empty means "whatever branch is currently checked out"."""

    commit_message: str = "tuinotes: update {title}"
    min_commit_interval: float = 10.0
    pull_on_start: bool = False


@dataclass
class TermuxConfig:
    """Termux:API integration. Everything degrades gracefully off-device."""

    notifications: bool = True
    clipboard: bool = True
    share: bool = True
    volume_keys: bool = True
    """Map ctrl+up/ctrl+down and pageup/pagedown for one-handed scrolling."""

    vibrate: bool = False
    keep_awake: bool = False
    voice: bool = True


@dataclass
class DailyConfig:
    """Daily-note behaviour (user story #2)."""

    enabled: bool = False
    template: str = "daily"
    title_format: str = "%Y-%m-%d"
    open_on_start: bool = False


@dataclass
class TrashConfig:
    retention_days: int = 30


@dataclass
class ExportConfig:
    html_template: str = "default"
    pdf_backend: str = "auto"
    """``auto``, ``pandoc`` or ``weasyprint``."""


@dataclass
class EncryptionConfig:
    gpg_binary: str = "gpg"
    recipients: List[str] = field(default_factory=_empty_list)
    cipher: str = "AES256"


@dataclass
class Config:
    """Top-level configuration object."""

    notes_dir: str = DEFAULT_NOTES_DIR
    theme: str = "tuinotes-dark"
    theme_light: str = "tuinotes-light"
    follow_system_theme: bool = False
    editor: EditorConfig = field(default_factory=EditorConfig)
    list: ListConfig = field(default_factory=ListConfig)
    git: GitConfig = field(default_factory=GitConfig)
    termux: TermuxConfig = field(default_factory=TermuxConfig)
    daily: DailyConfig = field(default_factory=DailyConfig)
    trash: TrashConfig = field(default_factory=TrashConfig)
    export: ExportConfig = field(default_factory=ExportConfig)
    encryption: EncryptionConfig = field(default_factory=EncryptionConfig)
    filename_date_prefix: bool = True
    filename_format: str = "%Y-%m-%d-{slug}.md"
    templates_dir: str = ""
    """Extra directory of ``*.md`` templates. Empty = ``<notes>/.templates`` only."""

    plugins: List[str] = field(default_factory=_empty_list)
    confirm_delete: bool = True
    startup_command: str = ""
    extra: Dict[str, Any] = field(default_factory=dict)
    """Unknown keys loaded from disk; kept so saves are lossless."""

    source: str = "defaults"
    """Where this config came from (never written to disk)."""

    # -- paths ------------------------------------------------------------
    @property
    def root(self) -> Path:
        """The notes vault directory."""
        return _expand(self.notes_dir)

    @property
    def config_file(self) -> Path:
        env = os.environ.get(ENV_CONFIG)
        if env:
            return _expand(env)
        return self.root / CONFIG_FILENAME

    @property
    def metadata_db(self) -> Path:
        return self.root / METADATA_FILENAME

    @property
    def trash_dir(self) -> Path:
        return self.root / TRASH_DIRNAME

    @property
    def templates_dir_path(self) -> Path:
        if self.templates_dir:
            return _expand(self.templates_dir)
        return self.root / TEMPLATES_DIRNAME

    # -- serialisation ----------------------------------------------------
    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data.pop("source", None)
        data.update(self.extra)
        data.pop("extra", None)
        return data

    def save(self, path: Optional[Path] = None) -> Path:
        """Write the config as pretty JSON (atomic)."""
        target = path or self.config_file
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n"
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_text(payload, encoding="utf-8")
        os.replace(tmp, target)
        return target

    def set(self, dotted: str, value: Any) -> None:
        """Set ``editor.line_numbers`` style keys, coercing to the field type."""
        parts = dotted.split(".")
        target: Any = self
        for part in parts[:-1]:
            target = getattr(target, part)
        leaf = parts[-1]
        current = getattr(target, leaf, None)
        setattr(target, leaf, _coerce(value, current))

    def get(self, dotted: str, default: Any = None) -> Any:
        target: Any = self
        for part in dotted.split("."):
            if is_dataclass(target):
                if not hasattr(target, part):
                    return default
                target = getattr(target, part)
            elif isinstance(target, Mapping) and part in target:
                target = target[part]
            else:
                return default
        return target


def _coerce(value: Any, current: Any) -> Any:
    """Coerce a CLI string to the type of the existing value."""
    if isinstance(current, bool):
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on", "y"}
        return bool(value)
    if isinstance(current, int) and not isinstance(current, bool):
        return int(value)
    if isinstance(current, float):
        return float(value)
    if isinstance(current, (list, tuple)):
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return list(value)
    return value


def _merge(target: Any, data: Mapping[str, Any], source: str) -> None:
    """Recursively apply a JSON mapping onto a dataclass instance."""
    valid = {f.name: f for f in fields(target) if f.name not in {"extra", "source"}}
    for key, value in data.items():
        if key in valid and is_dataclass(getattr(target, key, None)):
            if isinstance(value, Mapping):
                _merge(getattr(target, key), value, source)
            continue
        if key not in valid:
            if isinstance(getattr(target, "extra", None), dict):
                target.extra[key] = value
            continue
        if value is None:
            continue
        current = getattr(target, key)
        if isinstance(current, list):
            setattr(target, key, list(value))
        elif isinstance(current, bool):
            setattr(target, key, _coerce(value, current))
        elif isinstance(current, (int, float)) and isinstance(value, (int, float)):
            setattr(target, key, value)
        else:
            setattr(target, key, value)


def default_config_dir() -> Path:
    """``~/.config/tuinotes`` (or the platform config dir when available)."""
    env = os.environ.get("XDG_CONFIG_HOME")
    base = _expand(env) if env else Path.home() / ".config"
    return base / APP_NAME


def load_config(path: Optional[Path] = None, notes_dir: Optional[str] = None) -> Config:
    """Load configuration, applying the resolution order documented above."""
    config = Config()
    sources = []

    user_file = default_config_dir() / CONFIG_FILENAME
    if user_file.is_file():
        _merge(config, json.loads(user_file.read_text(encoding="utf-8")), str(user_file))
        sources.append(str(user_file))

    explicit_dir = notes_dir
    env_home = os.environ.get(ENV_HOME)
    if explicit_dir:
        config.notes_dir = explicit_dir
    elif env_home:
        config.notes_dir = env_home

    vault_file = path or config.config_file
    if vault_file.is_file():
        try:
            _merge(config, json.loads(vault_file.read_text(encoding="utf-8")), str(vault_file))
            sources.append(str(vault_file))
        except (json.JSONDecodeError, OSError):
            # A broken config must never stop you from reading your notes.
            pass

    # The file may carry its own notes_dir, but CLI/env overrides always win.
    if explicit_dir:
        config.notes_dir = explicit_dir
    elif env_home:
        config.notes_dir = env_home

    if os.environ.get(ENV_THEME):
        config.theme = os.environ[ENV_THEME]

    config.source = ", ".join(sources) if sources else "defaults"
    return config


def write_default_config(path: Path, notes_dir: Optional[str] = None) -> Path:
    """Write a fully-populated example config (used by ``tuinotes config init``)."""
    config = Config()
    if notes_dir:
        config.notes_dir = notes_dir
    return config.save(path)
