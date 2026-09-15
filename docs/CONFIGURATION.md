# Configuration guide

tuinotes reads plain JSON, in this order (later wins):

1. built-in defaults,
2. `~/.config/tuinotes/config.json` — user-global,
3. `~/notes/.config.json` — vault-level (syncs with your notes),
4. environment variables.

```bash
tuinotes config            # effective config + where it came from
tuinotes config init       # write a fully populated default to the vault
tuinotes config path       # which file is used
tuinotes config set editor.keymap=vim
```

Unknown keys are preserved when saving, so upgrading or downgrading never loses
settings.

## Environment variables

| variable | effect |
| --- | --- |
| `TUINOTES_HOME` | vault directory (overrides `notes_dir`) |
| `TUINOTES_CONFIG` | explicit config file path |
| `TUINOTES_THEME` | theme override |
| `VISUAL` / `EDITOR` | external editor used by `tuinotes edit` |
| `XDG_CONFIG_HOME` | where the user-global config lives |

## Full key reference

```jsonc
{
  "notes_dir": "~/notes",              // the vault
  "theme": "tuinotes-dark",            // see below
  "theme_light": "tuinotes-light",
  "follow_system_theme": false,
  "filename_date_prefix": true,        // YYYY-MM-DD-<slug>.md
  "filename_format": "%Y-%m-%d-{slug}.md",
  "templates_dir": "",                 // extra template folder (default <vault>/.templates)
  "confirm_delete": true,
  "startup_command": "",               // e.g. "daily"

  "editor": {
    "keymap": "normal",                // normal | vim | emacs
    "line_numbers": true,
    "soft_wrap": true,
    "tab_size": 4,
    "autosave": true,
    "autosave_interval": 3.0,          // seconds of quiet before writing
    "show_word_count": true,
    "highlight_tags": true,
    "syntax_highlight": true
  },

  "list": {
    "sort": "modified",                // modified | newest | oldest | alphabetical | size
    "page_size": 100,                  // rows loaded per batch
    "show_preview": true,
    "show_tags": true,
    "show_date": true,
    "fuzzy": true,                     // fuzzy rescue for typos
    "case_sensitive": false,
    "max_snippet": 160
  },

  "trash":   { "retention_days": 30 },

  "daily": {
    "enabled": false,                  // create today's note on startup
    "template": "daily",
    "title_format": "%Y-%m-%d",
    "open_on_start": false
  },

  "git": {
    "enabled": false,
    "auto_commit": true,               // commit after saves (debounced)
    "remote": "origin",
    "branch": "",                      // empty = current branch
    "commit_message": "tuinotes: update {title}",
    "min_commit_interval": 10.0,       // seconds between auto-commits
    "pull_on_start": false
  },

  "termux": {
    "notifications": true,             // "note saved" toasts
    "clipboard": true,
    "share": true,                     // Android share sheet
    "volume_keys": true,               // ctrl+up/down + pageup/pagedown scrolling
    "vibrate": false,
    "keep_awake": false,               // termux-wake-lock while the app runs
    "voice": true                      // termux-speech-to-text
  },

  "export": {
    "html_template": "default",
    "pdf_backend": "auto"              // auto | pandoc | weasyprint
  },

  "encryption": {
    "gpg_binary": "gpg",
    "recipients": [],                  // empty = symmetric passphrase
    "cipher": "AES256"
  },

  "plugins": []
}
```

## Themes

`tuinotes-dark` (default), `tuinotes-light`, `gruvbox-dark`, `gruvbox-light`, `nord`,
`monokai-tuinotes`, `solarized-dark`, `tokyo-night`, plus every Textual built-in.

Switch at runtime with `:theme nord` or `ctrl+shift+t`, or persistently with
`tuinotes config set theme=nord` / `TUINOTES_THEME=nord`.

## Git sync

```bash
cd ~/notes && tuinotes git init                 # repo + .gitignore for the index
git remote add origin git@github.com:you/notes.git
tuinotes config set git.enabled=true
tuinotes config set git.auto_commit=true
tuinotes git push
```

With `git.enabled` on, saves auto-commit (at most once per
`git.min_commit_interval` seconds) and `:git pull|push|status|log` work inside the app.
Conflicts are reported rather than auto-resolved — the files are yours.

## Encryption

```bash
tuinotes encrypt "Private note"      # -> <name>.md.gpg, original removed
tuinotes decrypt "Private note"
```

Encrypted notes appear in the list with a 🔒 and are never indexed, previewed or
included in search. Set `encryption.recipients` to use public-key encryption instead of
a passphrase.
