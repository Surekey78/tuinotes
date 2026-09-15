# Termux setup

tuinotes is built for a phone: startup is ~0.13 s, lists page lazily, and every
Android integration is optional.

## Install

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/Surekey78/tuinotes/main/scripts/install-termux.sh)
```

The script runs `pkg update`, installs `python`, `git` and `termux-api`, installs
tuinotes with pip, creates `~/notes`, adds the note-taking `extra-keys` row and
installs the Termux:Widget shortcuts. It is idempotent — run it again after updates.

Manual equivalent:

```bash
pkg update -y
pkg install -y python git termux-api
pip install termux-notes
mkdir -p ~/notes
tuinotes setup termux
tuinotes widget install
```

Install the **Termux:API** app from F-Droid (same source as Termux) for notifications,
clipboard, share, TTS and speech-to-text to work. `tuinotes doctor` tells you exactly
what is missing.

## One-handed typing: `extra-keys`

Termux cannot remap the hardware volume keys, so the supported setup is an on-screen
row plus in-app bindings:

```
tuinotes setup termux      # writes ~/.termux/termux.properties, then reloads settings
```

which adds:

```properties
extra-keys = [[ESC,'/',':',CTRL,ALT,LEFT,DOWN,UP,RIGHT,TAB,'-']]
```

That row gives you `/` (search), `:` (command mode), `CTRL` (chords) and the arrows
without leaving the keyboard. Inside tuinotes, `ctrl+up` / `ctrl+down` and
`pageup` / `pagedown` scroll half a page, so navigation works one-handed.

## Termux:Widget shortcuts

```bash
tuinotes widget install
```

creates in `~/.shortcuts`:

| shortcut | action |
| --- | --- |
| tuinotes-quick-note | dialog → `note "<text>"` → toast |
| tuinotes-daily-note | `tuinotes daily --open` |
| tuinotes-voice-note | `termux-speech-to-text` → note |
| tuinotes-share-to-note | shared text → note |

Open the Termux:Widget app to see them (long-press the home screen → widgets).

## Share sheet

```bash
tuinotes share               # capture whatever is shared into Termux as a note
tuinotes share --send "Tokio deep dive"
```

The `tuinotes-share-to-note` widget does the same from the widget screen.

## Voice notes

```bash
tuinotes voice               # dictate → new note
note --voice
```

Requires `termux-api` + the Termux:API app and microphone permission.

## Notifications & clipboard

```bash
tuinotes notify "Standup in 5" "bring the notes"
tuinotes clipboard           # capture the clipboard as a note
tuinotes clipboard --note "Tokio deep dive"
```

Saving a note posts a notification when `termux.notifications` is on (default).

## Storage access / import

```bash
termux-setup-storage                       # once, grants ~/storage
tuinotes new "Imported" -c "$(cat ~/storage/shared/note.md)"
# or copy files straight into the vault and reindex:
cp ~/storage/shared/*.md ~/notes/ && tuinotes reindex
```

## Syncing between phone and laptop

* **Git:** `tuinotes git init`, add a remote, `tuinotes config set git.enabled=true`.
* **Syncthing/Nextcloud:** point it at `~/notes`. Delete `.metadata.db` on a new device
  (or run `tuinotes reindex`) and the index rebuilds from the Markdown files.

## Troubleshooting

```bash
tuinotes doctor
```

reports the vault, index, FTS5 availability, git, gpg, pandoc, Termux:API and which
highlighter the editor is using.
