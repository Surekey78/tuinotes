# tuinotes

Fast, touch-friendly **Markdown notes in your terminal** — built for Termux on Android,
happy anywhere Python runs.

Plain `.md` files in `~/notes`, a SQLite index for instant search, a Textual TUI with a
vim-ish editor, and a `note` command that captures a thought in ~0.13 s.

```
$ note "the best error message is the one that never shows up" --tag idea
✓ the best error message is the one that never shows up  11 words  ~/notes/2026-09-15-the-best-error-message….md
```

---

## Install

```bash
pip install termux-notes        # from PyPI
# or, straight from git:
pip install "git+https://github.com/Surekey78/tuinotes"
# or, editable, for hacking:
git clone https://github.com/Surekey78/tuinotes && cd tuinotes && pip install -e .
```

Two commands are installed:

| command | what it does |
| --- | --- |
| `tuinotes` | the full TUI (no arguments) or a single subcommand |
| `note` | instant capture: `note "text"`, `note --daily`, `note --list` |

### Termux (Android)

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/Surekey78/tuinotes/main/scripts/install-termux.sh)
```

or by hand:

```bash
pkg update -y
pkg install -y python git ripgrep termux-api   # termux-api also needs the Termux:API app
pip install termux-notes
tuinotes setup termux      # adds a note-taking extra-keys row (/, :, CTRL, arrows)
tuinotes widget install    # Termux:Widget shortcuts: quick note, daily note, voice, share
tuinotes doctor            # sanity-check the environment
```

Optional extras:

* `pip install "termux-notes[syntax]"` — tree-sitter highlighting in the editor
  (Python ≥ 3.10). Without it tuinotes uses its **own built-in Markdown highlighter**,
  so headings, emphasis, code, `#tags` and `[[links]]` are coloured either way.
* `pkg install pandoc` (or `pip install weasyprint`) — PDF export.
* `pkg install gnupg` — encrypted notes.

---

## Quickstart

```bash
note "buy milk"                       # capture (0.13 s, no TUI)
note -t idea -t rust "async traits"   # capture with tags
tuinotes daily --open                 # today's note from a template
tuinotes                              # the app
```

Inside the app: `n` new · `enter` open · `/` search · `p` preview · `e` split ·
`d` delete · `s` sort · `t` tags · `g` graph · `:` command mode · `?` help.

User story, end to end:

```bash
$ tuinotes search "#rust async"
1.35 Tokio deep dive  now  #rust #reading
     See [Rust async notes] for the basics.
$ tuinotes graph --width 60
┌ cluster 1: 3 notes ─────┐
 Alpha ──▶ Beta           │
 Beta  ──▶ Gamma          │
└─────────────────────────┘
```

---

## Features

**Notes**

* Create, edit, rename, delete (to `.trash` with 30-day retention), restore.
* Markdown files named `YYYY-MM-DD-title.md`, atomic writes (temp file → `fsync` →
  `os.replace`), auto-save every 3 s while you type.
* Templates: `daily`, `meeting`, `idea`, `research`, `todo`, `journal`, `weekly`,
  `project` — plus your own in `~/notes/.templates/`.
* Daily note auto-creation (`tuinotes daily`, `:daily`, or the widget).

**Interface**

* Note list: live search, `#tag` chips, four sort orders, lazy paging (100 rows per
  batch) so 1 000+ notes open instantly.
* Editor: Markdown highlighting, toggleable line numbers, soft wrap, live word/char
  count, cursor position, save state, in-note find.
* Preview: rendered Markdown.
* Split view: edit + preview side by side, stacked automatically on a narrow screen.
* Themes: `tuinotes-dark`, `tuinotes-light`, `gruvbox-dark`, `gruvbox-light`, `nord`,
  `monokai-tuinotes`, `solarized-dark`, `tokyo-night` (`:theme nord`).
* Vim keymap (`hjkl`, `dd`, `x`, `o`, `w/b/e`, `yy/p`, `u`, `v`, `/`, `:w`, `:q`) and an
  Emacs keymap, toggleable with `:vim`.
* Command mode: `:tag idea`, `:sort newest`, `:export html`, `:git push`, `:template meeting`.
* Command palette (`ctrl+\` or `:palette`) for everything else.
* Touch bar with real buttons on the list screen, so nothing is keyboard-only.

**Search & organisation**

* Full-text search (SQLite FTS5, LIKE fallback) over titles, tags and bodies.
* Fuzzy rescue for typos (`grocer` → *Groceries*).
* `#hashtags`, `-#excluded`, `in:folder`, `title:word`, `"exact phrase"`.
* `[[wikilinks]]`, backlinks (`ctrl+b`) and a link graph with missing-target detection.

**Termux**

* Termux:API: notifications, clipboard, share-in/share-out, TTS, speech-to-text,
  vibrate, wake-lock.
* Termux:Widget shortcuts (`tuinotes widget install`).
* `extra-keys` row tuned for note taking (`tuinotes setup termux`).
* Everything degrades gracefully off-device — the same commands run on a laptop.

**Data & sync**

* Plain files: sync with Syncthing, Nextcloud, rclone, whatever you like.
* Optional Git: auto-commit on save (debounced), `:git pull|push|status|log`,
  conflict detection.
* Optional GPG encryption per note (`tuinotes encrypt <note>`); encrypted bodies are
  never indexed or previewed.

---

## CLI

```
tuinotes                          open the TUI
tuinotes new "Title" -t tag [--template meeting] [--open]
note "quick thought" [-t tag]     capture instantly
tuinotes daily [--open]           today's note
tuinotes list [--sort newest|oldest|alphabetical|modified|size] [-t tag] [--json]
tuinotes search "query" [-t tag] [--json]
tuinotes show <note> [--raw]      print / render a note
tuinotes edit <note> [--tui]      edit in $EDITOR or the TUI
tuinotes rename <note> "New title"
tuinotes tag <note> tag… [--remove]
tuinotes tags                     tags with counts
tuinotes backlinks <note>         links to and from a note
tuinotes graph [note] [--depth N]
tuinotes delete <note> [-y] [--permanent] / restore [id] / purge [--days N]
tuinotes export <note> --format html|md|txt|pdf [--out FILE] [--all DIR]
tuinotes encrypt|decrypt <note>
tuinotes templates [list|show NAME|install]
tuinotes git init|status|commit|push|pull|log
tuinotes config [show|set k=v|init|path]
tuinotes stats / reindex / doctor / version
tuinotes share [--send note] / notify / voice / clipboard
tuinotes widget install|uninstall|list
tuinotes setup termux|dirs
```

Every listing command takes `--json`, so tuinotes composes with `jq`, `fzf` and scripts:

```bash
tuinotes search "#rust" --json | jq -r '.[].title'
```

---

## Keybindings

Full reference: [docs/KEYBINDINGS.md](docs/KEYBINDINGS.md). Press `?` (or `f1`) in the app.
Termux specifics: [docs/TERMUX.md](docs/TERMUX.md). Example config:
[examples/config.json](examples/config.json).

| key | action |
| --- | --- |
| `ctrl+n` | new note |
| `ctrl+s` | save |
| `ctrl+f` or `/` | focus search |
| `ctrl+d` / `d` | delete (to trash) |
| `ctrl+p` / `p` | preview |
| `ctrl+e` / `e` | split view |
| `ctrl+g` / `g` | link graph |
| `ctrl+t` / `t` | tag filter |
| `s` | cycle sort order |
| `ctrl+r` | reindex |
| `:` | command mode |
| `?` / `f1` | help |
| `ctrl+\` | command palette (also `:palette`) |
| `esc` | back / cancel |
| `ctrl+q` | quit |

Editor extras: `ctrl+o` back · `ctrl+b` backlinks · `ctrl+l` line numbers ·
`ctrl+w` soft wrap · `ctrl+space` command bar.

---

## Configuration

Config is plain JSON, read from `~/.config/tuinotes/config.json` and then
`~/notes/.config.json` (vault-level wins, and syncs with your notes).

```bash
tuinotes config            # show the effective config
tuinotes config init       # write a fully documented default
tuinotes config set editor.keymap=vim
tuinotes config set editor.autosave_interval=2
tuinotes config set git.enabled=true
```

Common keys — full list in [docs/CONFIGURATION.md](docs/CONFIGURATION.md):

| key | default | meaning |
| --- | --- | --- |
| `notes_dir` | `~/notes` | the vault (`$TUINOTES_HOME` overrides) |
| `theme` | `tuinotes-dark` | any registered theme |
| `editor.keymap` | `normal` | `normal`, `vim` or `emacs` |
| `editor.line_numbers` | `true` | gutter |
| `editor.autosave` / `autosave_interval` | `true` / `3.0` | auto-save |
| `list.sort` | `modified` | default sort |
| `list.page_size` | `100` | rows loaded per batch |
| `trash.retention_days` | `30` | before purge |
| `git.enabled` / `git.auto_commit` | `false` / `true` | sync |
| `daily.template` | `daily` | daily-note template |

Environment: `TUINOTES_HOME` (vault), `TUINOTES_CONFIG` (config file),
`TUINOTES_THEME` (theme), `VISUAL`/`EDITOR` (external editor).

---

## Data layout

```
~/notes/
├── .metadata.db        # SQLite index (titles, tags, timestamps, FTS5) — rebuildable
├── .config.json        # vault-level preferences
├── .templates/         # your templates
├── .trash/             # deleted notes, 30-day retention
└── 2026-09-15-title.md # your notes
```

The database is a cache. Delete it (or run `tuinotes reindex`) and everything is
rebuilt from the Markdown files.

---

## Performance

Measured on this machine (x86_64, Python 3.11):

| operation | time |
| --- | --- |
| `note "text"` (capture + save + index) | 0.13 s |
| `tuinotes list` (cold start) | 0.13 s |
| importing the whole TUI | 0.26 s |
| indexing 300 notes | ~0.5 s (asserted < 30 s in the test suite) |
| listing 50 of 300 notes | < 1 s (asserted in the test suite) |

Large vaults page 100 rows at a time and only read note bodies when you open one.

---

## Development

```bash
pip install -e ".[dev]"
pytest                     # 143 tests: storage, search, CLI, templates, TUI (Textual pilot)
pytest tests/test_tui.py   # just the interface
ruff check src tests && mypy
```

The TUI tests drive the real app headlessly through Textual's pilot: they open notes,
type into the editor, verify auto-save hits the disk, exercise vim keys, filter by
search and `#tag`, and check the split view reflows on a narrow terminal.

---

## Roadmap / nice-to-haves

Done: templates, daily notes, HTML/PDF export, GPG encryption, backlinks, themes,
vim/emacs keymaps, Termux:Widget, voice capture, link graph, command mode.

Not yet: a plugin system, note-level version history UI, table-of-contents navigation.

## Licence

MIT — see [LICENSE](LICENSE).
