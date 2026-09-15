"""Optional Git sync for the vault.

Plain files mean Syncthing/Nextcloud already work; Git adds history and
multi-device editing (user story #4).  Everything shells out to ``git`` so
there is no extra dependency, and every call is defensive: a missing binary,
detached HEAD or offline remote never crashes the app, it just reports.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

from tuinotes.config import Config, GitConfig


class GitError(RuntimeError):
    """Raised when git cannot complete an operation."""


class GitUnavailable(GitError):
    """Raised when the ``git`` binary is missing."""


@dataclass(frozen=True)
class GitStatus:
    """A snapshot of ``git status --porcelain``."""

    is_repo: bool = False
    branch: str = ""
    dirty: bool = False
    ahead: int = 0
    behind: int = 0
    changed: Tuple[str, ...] = ()
    conflicts: Tuple[str, ...] = ()
    remote: str = ""
    error: str = ""

    @property
    def clean(self) -> bool:
        return self.is_repo and not self.dirty and not self.conflicts

    def describe(self) -> str:
        if not self.is_repo:
            return "not a git repository"
        parts = [f"branch {self.branch or 'detached'}"]
        if self.ahead:
            parts.append(f"↑{self.ahead}")
        if self.behind:
            parts.append(f"↓{self.behind}")
        if self.conflicts:
            parts.append(f"{len(self.conflicts)} conflict(s)")
        elif self.dirty:
            parts.append(f"{len(self.changed)} change(s)")
        else:
            parts.append("clean")
        return " · ".join(parts)


@dataclass
class GitSync:
    """Small, testable wrapper around ``git`` for one vault."""

    root: Path
    config: GitConfig = field(default_factory=GitConfig)
    _last_commit: float = field(default=0.0, init=False, repr=False)

    # ------------------------------------------------------------------ basics
    @staticmethod
    def available() -> bool:
        return shutil.which("git") is not None

    def run(
        self,
        *args: str,
        check: bool = True,
        timeout: float = 60.0,
        input_text: Optional[str] = None,
    ) -> subprocess.CompletedProcess:
        if not self.available():
            raise GitUnavailable("git is not installed (on Termux: pkg install git)")
        env = dict(os.environ)
        env.update(
            {
                "GIT_PAGER": "cat",
                "PAGER": "cat",
                "GIT_TERMINAL_PROMPT": "0",
                "LC_ALL": env.get("LC_ALL", "C.UTF-8"),
            }
        )
        try:
            result = subprocess.run(
                ["git", "-C", str(self.root), *args],
                capture_output=True,
                text=True,
                timeout=timeout,
                input=input_text,
                env=env,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise GitError(f"git {' '.join(args)} timed out after {timeout}s") from exc
        if check and result.returncode != 0:
            raise GitError(result.stderr.strip() or f"git {' '.join(args)} failed")
        return result

    def is_repo(self) -> bool:
        if not self.available():
            return False
        result = self.run("rev-parse", "--is-inside-work-tree", check=False)
        return result.returncode == 0 and result.stdout.strip() == "true"

    def init(self, branch: str = "main") -> str:
        """Initialise a repo (idempotent) with a sane ``.gitignore``."""
        self.root.mkdir(parents=True, exist_ok=True)
        if self.is_repo():
            return f"already a repository on {self.branch() or branch}"
        self.run("init", "-b", branch, check=False) or self.run("init", check=False)
        self.write_gitignore()
        self.run("add", "-A", check=False)
        self.run("-c", "user.name=tuinotes", "-c", "user.email=tuinotes@localhost",
                 "commit", "-m", "tuinotes: initial commit", check=False)
        return f"initialised repository in {self.root}"

    def write_gitignore(self) -> Path:
        """Ignore the index and temp files, keep notes and config."""
        target = self.root / ".gitignore"
        body = "\n".join(
            [
                "# tuinotes",
                ".metadata.db",
                ".metadata.db-wal",
                ".metadata.db-shm",
                "*.tmp*",
                ".DS_Store",
            ]
        )
        existing = target.read_text(encoding="utf-8") if target.is_file() else ""
        if ".metadata.db" in existing:
            return target
        target.write_text((existing.rstrip() + "\n\n" if existing.strip() else "") + body + "\n",
                          encoding="utf-8")
        return target

    def branch(self) -> str:
        result = self.run("rev-parse", "--abbrev-ref", "HEAD", check=False)
        return result.stdout.strip() if result.returncode == 0 else ""

    def remote_url(self, remote: Optional[str] = None) -> str:
        remote = remote or self.config.remote
        result = self.run("remote", "get-url", remote, check=False)
        return result.stdout.strip() if result.returncode == 0 else ""

    # ------------------------------------------------------------------ status
    def status(self) -> GitStatus:
        if not self.is_repo():
            return GitStatus(is_repo=False)
        porcelain = self.run("status", "--porcelain=v1", "-b", check=False)
        lines = [line for line in porcelain.stdout.splitlines() if line.strip()]
        branch = self.branch()
        ahead = behind = 0
        changed: List[str] = []
        conflicts: List[str] = []
        for line in lines:
            if line.startswith("##"):
                if "[ahead " in line:
                    try:
                        ahead = int(line.split("[ahead ")[1].split("]")[0].split(",")[0])
                    except (IndexError, ValueError):
                        ahead = 0
                if "behind " in line:
                    try:
                        behind = int(line.split("behind ")[1].split("]")[0].split(",")[0])
                    except (IndexError, ValueError):
                        behind = 0
                continue
            code, _, path = line[:2], line[2:3], line[3:].strip()
            if code.strip() in {"UU", "AA", "DD", "AU", "UA", "DU", "UD"}:
                conflicts.append(path)
            else:
                changed.append(path)
        return GitStatus(
            is_repo=True,
            branch=branch,
            dirty=bool(changed) or bool(conflicts),
            ahead=ahead,
            behind=behind,
            changed=tuple(changed),
            conflicts=tuple(conflicts),
            remote=self.config.remote,
        )

    # ----------------------------------------------------------------- commits
    def add_all(self) -> None:
        self.run("add", "-A")

    def commit(self, message: str, *, allow_empty: bool = False) -> bool:
        """Commit staged changes. Returns ``True`` when a commit was created."""
        self.add_all()
        status = self.status()
        if not status.dirty and not allow_empty:
            return False
        args = ["-c", "user.name=tuinotes", "-c", "user.email=tuinotes@localhost", "commit", "-m", message]
        if allow_empty:
            args.append("--allow-empty")
        result = self.run(*args, check=False)
        return result.returncode == 0

    def auto_commit(self, title: str = "notes", *, force: bool = False) -> Optional[str]:
        """Commit if enabled, dirty, and the debounce window has elapsed."""
        if not self.config.enabled or not self.config.auto_commit:
            return None
        if not force and time.time() - self._last_commit < self.config.min_commit_interval:
            return None
        if not self.is_repo():
            return None
        message = self.config.commit_message.format(title=title)
        if self.commit(message):
            self._last_commit = time.time()
            return message
        return None

    # ------------------------------------------------------------------ remote
    def pull(self, *, rebase: bool = True) -> str:
        branch = self.config.branch or self.branch()
        args = ["pull"]
        if rebase:
            args.append("--rebase")
        args += [self.config.remote, branch] if branch else [self.config.remote]
        result = self.run(*args, check=False, timeout=120.0)
        if result.returncode != 0:
            error = (result.stderr or result.stdout).strip()
            if "conflict" in error.lower():
                raise GitError("pull produced conflicts — resolve them, then run :git commit")
            raise GitError(error or "pull failed")
        return (result.stdout or "").strip() or "up to date"

    def push(self) -> str:
        branch = self.config.branch or self.branch()
        args = ["push"]
        args += [self.config.remote, branch] if branch else [self.config.remote]
        result = self.run(*args, check=False, timeout=120.0)
        if result.returncode != 0:
            raise GitError((result.stderr or result.stdout).strip() or "push failed")
        return (result.stdout or result.stderr or "pushed").strip()

    def fetch(self) -> str:
        result = self.run("fetch", self.config.remote, check=False, timeout=120.0)
        if result.returncode != 0:
            raise GitError((result.stderr or result.stdout).strip() or "fetch failed")
        return "fetched"

    def conflicts(self) -> List[str]:
        result = self.run("diff", "--name-only", "--diff-filter=U", check=False)
        return [line.strip() for line in result.stdout.splitlines() if line.strip()]

    def log(self, limit: int = 10) -> List[str]:
        result = self.run(
            "log",
            f"-{max(1, min(limit, 200))}",
            "--pretty=format:%h %ad %s",
            "--date=short",
            check=False,
        )
        return [line for line in result.stdout.splitlines() if line.strip()]

    def history(self, path: str, limit: int = 10) -> List[str]:
        result = self.run(
            "log",
            f"-{max(1, min(limit, 200))}",
            "--pretty=format:%h %ad %s",
            "--date=short",
            "--",
            path,
            check=False,
        )
        return [line for line in result.stdout.splitlines() if line.strip()]


def from_config(config: Config) -> GitSync:
    """Build a :class:`GitSync` bound to a loaded config."""
    return GitSync(root=config.root, config=config.git)
