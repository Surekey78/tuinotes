"""Configuration loading, saving and coercion."""

from __future__ import annotations

import json

from tuinotes.config import Config, load_config, write_default_config


def test_defaults_are_mobile_friendly():
    config = Config()
    assert config.editor.autosave is True
    assert config.editor.autosave_interval == 3.0
    assert config.list.page_size == 100
    assert config.trash.retention_days == 30
    assert config.notes_dir == "~/notes"


def test_paths_follow_the_vault(tmp_path):
    config = Config(notes_dir=str(tmp_path / "vault"))
    assert config.root == (tmp_path / "vault").resolve()
    assert config.metadata_db.name == ".metadata.db"
    assert config.trash_dir.name == ".trash"
    assert config.templates_dir_path.name == ".templates"


def test_save_and_reload_roundtrip(tmp_path):
    config = Config(notes_dir=str(tmp_path / "vault"))
    config.editor.keymap = "vim"
    config.editor.line_numbers = False
    config.git.enabled = True
    config.git.remote = "backup"
    config.list.sort = "alphabetical"
    path = config.save()
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["editor"]["keymap"] == "vim"
    assert raw["git"]["remote"] == "backup"

    reloaded = load_config(notes_dir=str(tmp_path / "vault"))
    assert reloaded.editor.keymap == "vim"
    assert reloaded.editor.line_numbers is False
    assert reloaded.git.enabled is True
    assert reloaded.list.sort == "alphabetical"


def test_unknown_keys_survive_a_save(tmp_path):
    config = Config(notes_dir=str(tmp_path / "vault"))
    path = config.save()
    data = json.loads(path.read_text(encoding="utf-8"))
    data["future_option"] = {"nested": True}
    path.write_text(json.dumps(data), encoding="utf-8")

    reloaded = load_config(notes_dir=str(tmp_path / "vault"))
    assert reloaded.extra["future_option"] == {"nested": True}
    reloaded.save()
    assert json.loads(path.read_text(encoding="utf-8"))["future_option"] == {"nested": True}


def test_dotted_set_coerces_types(tmp_path):
    config = Config(notes_dir=str(tmp_path / "vault"))
    config.set("editor.line_numbers", "false")
    assert config.editor.line_numbers is False
    config.set("editor.autosave_interval", "5")
    assert config.editor.autosave_interval == 5.0
    config.set("trash.retention_days", "7")
    assert config.trash.retention_days == 7
    config.set("encryption.recipients", "me@example.com, you@example.com")
    assert config.encryption.recipients == ["me@example.com", "you@example.com"]
    assert config.get("editor.keymap") == "normal"
    assert config.get("does.not.exist", "fallback") == "fallback"


def test_environment_overrides_the_vault(tmp_path, monkeypatch):
    monkeypatch.setenv("TUINOTES_HOME", str(tmp_path / "env-vault"))
    config = load_config()
    assert config.root == (tmp_path / "env-vault").resolve()


def test_environment_overrides_the_theme(tmp_path, monkeypatch):
    monkeypatch.setenv("TUINOTES_THEME", "nord")
    assert load_config().theme == "nord"


def test_broken_config_file_does_not_crash(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / ".config.json").write_text("{not json", encoding="utf-8")
    config = load_config(notes_dir=str(vault))
    assert config.editor.autosave is True


def test_write_default_config(tmp_path):
    target = tmp_path / "config.json"
    write_default_config(target, notes_dir=str(tmp_path / "vault"))
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["editor"]["autosave_interval"] == 3.0
    assert "source" not in data


def test_environment_wins_over_the_vault_config(tmp_path, monkeypatch):
    # The default vault is $HOME/notes, and HOME points at tmp_path in tests.
    default_vault = tmp_path / "notes"
    default_vault.mkdir()
    (default_vault / ".config.json").write_text(
        '{"notes_dir": "~/somewhere-else"}', encoding="utf-8"
    )

    monkeypatch.setenv("TUINOTES_HOME", str(tmp_path / "env-vault"))
    assert load_config().root == (tmp_path / "env-vault").resolve()

    # Without the override, the file's own notes_dir is honoured.
    monkeypatch.delenv("TUINOTES_HOME")
    assert load_config().root == (tmp_path / "somewhere-else").resolve()


def test_cli_vault_wins_over_the_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("TUINOTES_HOME", str(tmp_path / "env-vault"))
    assert load_config(notes_dir=str(tmp_path / "cli-vault")).root == (
        tmp_path / "cli-vault"
    ).resolve()
