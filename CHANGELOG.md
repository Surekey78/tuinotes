# Changelog

## 0.1.0 — first release

**Core**

* Markdown vault in `~/notes` with atomic writes (`temp → fsync → os.replace`).
* SQLite index (`.metadata.db`) with FTS5 full-text search and a LIKE fallback;
  the index is a rebuildable cache (`tuinotes reindex`).
* Create, edit, rename, delete-to-trash (30-day retention), restore, purge.
* `YYYY-MM-DD-title.md` filenames, unique on collision.
* Auto-save every 3 s (configurable) while editing.

**Interface (Textual)**

* Note list with live search, `#tag` chips, five sort orders and lazy paging.
* Markdown editor with a built-in highlighter (tree-sitter when
  `termux-notes[syntax]` is installed), line numbers, soft wrap, live counts.
* Rendered preview, split view (stacks on narrow screens), link graph.
* Vim and Emacs keymaps, `:command` mode, command palette, eight themes.
* Touch bar with buttons for the common actions.

**Search & links**

* FTS5 + fuzzy search, `#tag`, `-#tag`, `in:folder`, `title:word`, `"phrase"`.
* `[[wikilinks]]`, backlinks, outgoing links, missing-target detection.

**Integrations**

* Termux:API: notifications, clipboard, share in/out, TTS, speech-to-text,
  vibrate, wake-lock; Termux:Widget shortcuts; `extra-keys` setup.
* Git sync with debounced auto-commit and conflict reporting.
* GPG encryption per note (bodies never indexed).
* Export to HTML (built in), Markdown, plain text and PDF (pandoc/weasyprint).

**CLI**

* `tuinotes` (TUI + 25 subcommands) and `note` (instant capture, ~0.13 s).
* `--json` on every listing command for scripting.

**Tests**

* 138 tests: Markdown parsing, config, storage, search, commands, graph,
  templates, exporter, CLI end-to-end, and the TUI driven by Textual's pilot.
