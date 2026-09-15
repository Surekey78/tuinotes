"""A pragmatic Vim layer for the editor.

Textual's TextArea has no modal editing, so this module implements one: in
``NORMAL`` mode the TextArea is switched to read-only (which makes it stop
consuming key events), and every key is interpreted here.  ``INSERT`` mode hands
control back to the widget.

Supported: ``hjkl`` ``w b e`` ``0 $`` ``gg G`` ``ctrl+d/u/f/b``, counts
(``3j``), ``i I a A o O``, ``x dd dw D cc cw``, ``yy yw p P``, ``u ctrl+r``,
``v`` (line-wise visual), ``/ ? n N``, ``:`` and ``Esc``.
"""

from __future__ import annotations

from typing import Callable, List, Optional, Tuple

from textual.widgets import TextArea

Location = Tuple[int, int]
Callback = Callable[[str], None]

NORMAL = "normal"
INSERT = "insert"
VISUAL = "visual"


class VimMode:
    """Modal editing controller bound to a TextArea."""

    def __init__(
        self,
        area: TextArea,
        *,
        on_search: Optional[Callback] = None,
        on_command: Optional[Callback] = None,
        on_status: Optional[Callback] = None,
    ) -> None:
        self.area = area
        self.on_search = on_search
        self.on_command = on_command
        self.on_status = on_status
        self.mode: str = NORMAL
        self._count: str = ""
        self._pending: str = ""
        self.register: str = ""
        self.last_search: str = ""
        self._search_forward: bool = True
        self._selection_anchor: Optional[Location] = None

    # ------------------------------------------------------------------- state
    @property
    def count(self) -> int:
        return int(self._count) if self._count.isdigit() and int(self._count) > 0 else 1

    def status_text(self) -> str:
        if self.mode == INSERT:
            return "INSERT"
        label = "NORMAL" if self.mode == NORMAL else "VISUAL"
        if self._pending:
            label += f" {self._pending}"
        return label

    def enter(self, mode: str = NORMAL) -> None:
        """Switch modes, keeping the TextArea focused and editable when needed."""
        self.mode = mode
        self._pending = ""
        self._count = ""
        if mode == INSERT:
            self.area.read_only = False
        else:
            self.area.read_only = True
            self._selection_anchor = None
        self.area.focus()
        if self.on_status:
            self.on_status(self.status_text())

    def toggle(self) -> None:
        self.enter(INSERT if self.mode != INSERT else NORMAL)

    # ------------------------------------------------------------------- input
    def handle_key(self, key: str) -> bool:
        """Handle a key in NORMAL/VISUAL mode. Returns ``True`` when consumed."""
        if self.mode == INSERT:
            return False

        if key == "escape":
            if self.mode == VISUAL:
                self.enter(NORMAL)
                return True
            self._pending = ""
            self._count = ""
            return True

        if key.isdigit() and not (key == "0" and not self._count):
            self._count += key
            return True

        if self._pending:
            return self._apply_operator(self._pending, key)

        handler = getattr(self, f"_key_{key.replace('+', '_')}", None)
        if handler is not None:
            handler()
            if not self._pending:
                self._count = ""
            return True
        return False

    # --------------------------------------------------------------- operators
    def _apply_operator(self, operator: str, key: str) -> bool:
        self._pending = ""
        if key == "escape":
            self._count = ""
            return True
        if operator == "g":
            if key == "g":
                self._count = ""
                self._move((0, 0))
            return True
        count = self.count
        self._count = ""
        if operator == "d":
            return self._delete_motion(key, count, insert_after=False)
        if operator == "c":
            return self._delete_motion(key, count, insert_after=True)
        if operator == "y":
            return self._yank_motion(key, count)
        return True

    def _delete_motion(self, key: str, count: int, *, insert_after: bool) -> bool:
        start = self.area.cursor_location
        if key in {"d", "c"}:  # dd / cc — whole line(s), no motion lookup
            row = start[0]
            last = self.area.document.line_count - 1
            if row >= last and row > 0:
                start = (row - 1, len(self._line(row - 1)))
                end = (row, len(self._line(row)))
            else:
                end = (min(row + count, last + 1), 0)
                if row + count > last:
                    end = (last, len(self._line(last)))
            text = self.area.get_text_range(start, end)
            self.register = text
            self._edit(lambda: self.area.delete(start, end))
            if insert_after:
                self.enter(INSERT)
            return True
        target = self._motion_target(key, count)
        if target is None:
            return True
        if key in {"$", "D"}:
            target = (start[0], len(self._line(start[0])))
        text = self.area.get_text_range(start, target)  # type: ignore[arg-type]
        self.register = text
        self._edit(lambda: self.area.delete(start, target))
        if insert_after:
            self.enter(INSERT)
        return True

    def _yank_motion(self, key: str, count: int) -> bool:
        start = self.area.cursor_location
        if key in {"y", "$"}:
            if key == "y":
                row = start[0]
                last = self.area.document.line_count - 1
                end = (min(row + count, last + 1), 0)
                if row + count > last:
                    end = (last, len(self._line(last)))
            else:
                end = (start[0], len(self._line(start[0])))
        else:
            end = self._motion_target(key, count) or start
        self.register = self.area.get_text_range(start, end)  # type: ignore[arg-type]
        self._notify(f'yanked "{self.register[:40]}"')
        return True

    def _motion_target(self, key: str, count: int) -> Optional[Location]:
        if key == "w":
            return self._repeat(lambda: self.area.get_cursor_word_right_location(), count)
        if key in {"b", "e"}:
            if key == "b":
                return self._repeat(lambda: self.area.get_cursor_word_left_location(), count)
            return self._repeat(lambda: self.area.get_cursor_word_right_location(), count)
        if key == "$":
            return (self.area.cursor_location[0], len(self._line(self.area.cursor_location[0])))
        if key == "0":
            return (self.area.cursor_location[0], 0)
        return None

    def _repeat(self, fn: Callable[[], Location], count: int) -> Location:
        result = self.area.cursor_location
        for _ in range(max(1, count)):
            result = fn()
        return result

    # -------------------------------------------------------------------- keys
    def _key_h(self) -> bool:
        row, col = self.area.cursor_location
        return self._move((row, max(0, col - self.count)))

    def _key_l(self) -> bool:
        row, col = self.area.cursor_location
        limit = len(self._line(row))
        return self._move((row, min(limit, col + self.count)))

    def _key_j(self) -> bool:
        return self._move(self._repeat(lambda: self.area.get_cursor_down_location(), self.count))

    def _key_k(self) -> bool:
        return self._move(self._repeat(lambda: self.area.get_cursor_up_location(), self.count))

    def _key_w(self) -> bool:
        return self._move(self._motion_target("w", self.count) or self.area.cursor_location)

    def _key_b(self) -> bool:
        return self._move(self._motion_target("b", self.count) or self.area.cursor_location)

    def _key_e(self) -> bool:
        return self._move(self._motion_target("e", self.count) or self.area.cursor_location)

    def _key_0(self) -> bool:
        return self._move((self.area.cursor_location[0], 0))

    def _key_dollar_sign(self) -> bool:
        row = self.area.cursor_location[0]
        return self._move((row, len(self._line(row))))

    def _key_g(self) -> bool:
        self._pending = "g"
        return True

    def _key_G(self) -> bool:
        last = self.area.document.line_count - 1
        return self._move((last, 0))

    def _key_ctrl_d(self) -> bool:
        return self._move(self._page(0.5))

    def _key_ctrl_u(self) -> bool:
        return self._move(self._page(-0.5))

    def _key_ctrl_f(self) -> bool:
        return self._move(self._page(1.0))

    def _key_ctrl_b(self) -> bool:
        return self._move(self._page(-1.0))

    def _page(self, factor: float) -> Location:
        try:
            height = self.area.size.height or 20
        except Exception:  # pragma: no cover - before mount
            height = 20
        step = max(1, int(height * factor))
        row, col = self.area.cursor_location
        last = self.area.document.line_count - 1
        return (max(0, min(last, row + step * self.count)), col)

    def _key_i(self) -> bool:
        self.enter(INSERT)
        return True

    def _key_I(self) -> bool:
        self._move((self.area.cursor_location[0], 0))
        self.enter(INSERT)
        return True

    def _key_a(self) -> bool:
        row, col = self.area.cursor_location
        self._move((row, min(len(self._line(row)), col + 1)))
        self.enter(INSERT)
        return True

    def _key_A(self) -> bool:
        row = self.area.cursor_location[0]
        self._move((row, len(self._line(row))))
        self.enter(INSERT)
        return True

    def _key_o(self) -> bool:
        row, _ = self.area.cursor_location
        line_end = (row, len(self._line(row)))
        self.enter(INSERT)
        self._edit(lambda: self.area.insert("\n", line_end))
        self.area.move_cursor((row + 1, 0))
        return True

    def _key_O(self) -> bool:
        row, _ = self.area.cursor_location
        self.enter(INSERT)
        self._edit(lambda: self.area.insert("\n", (row, 0)))
        self.area.move_cursor((row, 0))
        return True

    def _key_x(self) -> bool:
        row, col = self.area.cursor_location
        line = self._line(row)
        if col >= len(line):
            return True
        end = (row, min(len(line), col + self.count))
        self.register = self.area.get_text_range((row, col), end)
        self._edit(lambda: self.area.delete((row, col), end))
        return True

    def _key_d(self) -> bool:
        self._pending = "d"
        return False

    def _key_c(self) -> bool:
        self._pending = "c"
        return False

    def _key_y(self) -> bool:
        self._pending = "y"
        return False

    def _key_D(self) -> bool:
        row, col = self.area.cursor_location
        line = self._line(row)
        if col >= len(line):
            return True
        self.register = self.area.get_text_range((row, col), (row, len(line)))
        self._edit(lambda: self.area.delete((row, col), (row, len(line))))
        return True

    def _key_u(self) -> bool:
        for _ in range(self.count):
            self._edit(lambda: self.area.undo())
        return True

    def _key_ctrl_r(self) -> bool:
        for _ in range(self.count):
            self._edit(lambda: self.area.redo())
        return True

    def _key_p(self) -> bool:
        if not self.register:
            return True
        row, col = self.area.cursor_location
        location = (row, min(len(self._line(row)), col + 1))
        text = self.register
        self._edit(lambda: self.area.insert(text, location))
        return True

    def _key_P(self) -> bool:
        if not self.register:
            return True
        location = self.area.cursor_location
        text = self.register
        self._edit(lambda: self.area.insert(text, location))
        return True

    def _key_v(self) -> bool:
        if self.mode == VISUAL:
            self.enter(NORMAL)
            return True
        self.enter(VISUAL)
        row = self.area.cursor_location[0]
        self._selection_anchor = (row, 0)
        self.area.select_line(row)
        return True

    def _key_slash(self) -> bool:
        self._search_forward = True
        if self.on_search:
            self.on_search("/")
        return True

    def _key_question_mark(self) -> bool:
        self._search_forward = False
        if self.on_search:
            self.on_search("?")
        return True

    def _key_n(self) -> bool:
        return self._search_repeat(forward=self._search_forward)

    def _key_N(self) -> bool:
        return self._search_repeat(forward=not self._search_forward)

    def _key_colon(self) -> bool:
        if self.on_command:
            self.on_command(":")
        return True

    # ----------------------------------------------------------------- helpers
    def run_search(self, needle: str, forward: Optional[bool] = None) -> bool:
        """Jump to the next occurrence of ``needle`` (used by ``/``)."""
        if not needle:
            return False
        self.last_search = needle
        if forward is not None:
            self._search_forward = forward
        return self._search_repeat(forward=self._search_forward, first=True)

    def _search_repeat(self, forward: bool, first: bool = False) -> bool:
        needle = self.last_search
        if not needle:
            self._notify("no search pattern")
            return True
        text = self.area.text
        row, col = self.area.cursor_location
        offset = self.area.document.get_index_from_location((row, col))  # type: ignore[attr-defined]
        haystack = text.lower()
        target = needle.lower()
        if not first:
            offset += 1 if forward else -1
        found = haystack.find(target, offset) if forward else haystack.rfind(target, 0, max(offset, 0))
        if found == -1:
            found = haystack.find(target) if forward else haystack.rfind(target)
        if found == -1:
            self._notify(f'"{needle}" not found')
            return True
        location = self.area.document.get_location_from_index(found)  # type: ignore[attr-defined]
        self.area.move_cursor(location, center=True)
        return True

    def _move(self, location: Location) -> bool:
        if self.mode == VISUAL and self._selection_anchor is not None:
            self.area.move_cursor(location, select=True)
        else:
            self.area.move_cursor(location)
        return True

    def _line(self, index: int) -> str:
        try:
            return self.area.get_line(index).plain
        except IndexError:
            return ""

    def _edit(self, operation: Callable[[], object]) -> None:
        """Apply an edit even while the widget is read-only (NORMAL mode)."""
        was_read_only = self.area.read_only
        self.area.read_only = False
        try:
            operation()
        finally:
            self.area.read_only = was_read_only

    def _notify(self, message: str) -> None:
        if self.on_status:
            self.on_status(message)

    def describe(self) -> List[str]:
        """Keybinding reference rows for the help screen."""
        return [
            "hjkl / w b e — move",
            "0 $ gg G — line & file jumps",
            "i I a A o O — insert",
            "x dd dw D — delete",
            "cc cw — change",
            "yy yw p P — yank & paste",
            "u ctrl+r — undo & redo",
            "v — visual line",
            "/ ? n N — search",
            ": — command mode",
            "Esc — back to normal",
        ]
