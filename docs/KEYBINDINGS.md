# Keybinding reference

Press `?` or `f1` inside tuinotes for the same list; `ctrl+\` (or `:palette`) opens the command palette.

## Everywhere

| key | action |
| --- | --- |
| `ctrl+n` | new note |
| `ctrl+s` | save |
| `ctrl+f` | focus search |
| `ctrl+d` | delete note (to trash) |
| `ctrl+p` | toggle preview |
| `ctrl+e` | split view (edit + preview) |
| `ctrl+g` | link graph |
| `ctrl+t` | tag filter |
| `ctrl+r` | reindex / refresh |
| `ctrl+q` | quit |
| `?` or `f1` | help |
| `ctrl+\` | command palette (also `:palette`) |
| `ctrl+shift+t` | cycle theme |
| `esc` | back / cancel |

## Note list

| key | action |
| --- | --- |
| `enter` | open the highlighted note |
| `/` | search (`#tag`, `-#tag`, `in:folder`, `title:word`, `"phrase"`) |
| `n` | new note |
| `d` | delete |
| `p` | preview |
| `e` | split view |
| `g` | graph |
| `s` | cycle sort order (modified → newest → oldest → a→z → size) |
| `t` | tag filter prompt |
| `r` | rename |
| `j` / `k`, `↓` / `↑` | move |
| `ctrl+l` | load every row (no paging) |
| `tab` | jump to the touch buttons |
| `:` | command mode |
| `q` | quit |

## Editor

| key | action |
| --- | --- |
| `ctrl+s` | save now |
| `ctrl+p` | preview |
| `ctrl+e` | split view |
| `ctrl+b` | backlinks |
| `ctrl+o` | back to the list (saves first) |
| `ctrl+l` | toggle line numbers |
| `ctrl+w` | toggle soft wrap |
| `ctrl+t` | add tags |
| `ctrl+g` | graph |
| `ctrl+space` | focus the command bar |
| `esc` | leave insert mode → leave the command bar → go back |

The command bar at the bottom of the editor runs `:commands`; anything you type that
does not start with `:` is treated as an in-note search.

## Vim keymap (`editor.keymap = "vim"`, toggle with `:vim`)

| key | action |
| --- | --- |
| `h j k l` | move (counts allowed: `3j`) |
| `w b e` | word motions |
| `0 $ gg G` | line / file jumps |
| `ctrl+d ctrl+u ctrl+f ctrl+b` | half / full page |
| `i I a A o O` | enter insert mode |
| `x` | delete character |
| `dd dw D` | delete line / word / to end of line |
| `cc cw` | change line / word |
| `yy yw p P` | yank and paste |
| `u` / `ctrl+r` | undo / redo |
| `v` | line-wise visual |
| `/` `?` `n` `N` | search |
| `:` | command mode |
| `esc` | back to normal mode |

## Emacs keymap (`editor.keymap = "emacs"`)

Standard TextArea editing keys plus `ctrl+a` (line start), `ctrl+e` (line end),
`ctrl+k` (kill to end of line), `ctrl+w` (delete word left), `ctrl+u` (delete to line
start).

## Search syntax

| syntax | meaning |
| --- | --- |
| `#tag` | only notes with this tag |
| `-#tag` | exclude a tag |
| `in:folder` | restrict to a sub-folder |
| `title:word` | search titles only |
| `"exact phrase"` | phrase match |

## `:commands`

`:w` `:q` `:wq` `:q!` · `:n [title]` `:e <note>` `:d [note]` `:restore <id>` ·
`:s <query>` · `:tag <tag…>` `:untag <tag…>` `:tags` · `:sort <key>` · `:theme <name>` ·
`:daily` `:template <name>` `:templates` · `:preview` `:split` `:backlinks` `:graph` ·
`:rename <title>` · `:export html|md|txt|pdf [path]` ·
`:git status|commit|push|pull|log|init` · `:set <key> <value>` ·
`:numbers` `:vim` `:wrap` · `:share` `:voice` · `:reindex` `:trash` `:purge [days]` ·
`:reload` `:help` `:version`
