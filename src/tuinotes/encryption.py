"""Optional GPG encryption for individual notes.

Encrypted notes are stored as ``<name>.md.gpg`` next to their siblings, so the
vault stays a plain folder that syncs with anything.  Their bodies are never
indexed, never previewed and never leave the device in plaintext on disk.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from tuinotes.config import EncryptionConfig

GPG_SUFFIX = ".gpg"


class EncryptionError(RuntimeError):
    """Raised when gpg is missing or refuses to do its job."""


def available(binary: str = "gpg") -> bool:
    return shutil.which(binary) is not None


def is_encrypted(path: Path | str) -> bool:
    return str(path).lower().endswith(GPG_SUFFIX)


def _run(
    binary: str,
    args: list[str],
    *,
    input_bytes: Optional[bytes] = None,
    passphrase: Optional[str] = None,
) -> subprocess.CompletedProcess:
    if not available(binary):
        raise EncryptionError(f"{binary} not found (on Termux: pkg install gnupg)")
    full = [binary, "--batch", "--yes", "--quiet"]
    if passphrase is not None:
        full += ["--pinentry-mode", "loopback", "--passphrase", passphrase]
    full += args
    return subprocess.run(full, input=input_bytes, capture_output=True, check=False)


def encrypt_text(
    text: str, target: Path, config: Optional[EncryptionConfig] = None
) -> Path:
    """Encrypt ``text`` into ``target`` (which must end in ``.gpg``)."""
    config = config or EncryptionConfig()
    if not is_encrypted(target):
        target = Path(str(target) + GPG_SUFFIX)
    recipients: list[str] = []
    for recipient in config.recipients:
        recipients += ["--recipient", recipient]
    args: list[str] = []
    if recipients:
        args += recipients + ["--trust-model", "always", "--encrypt"]
    else:
        args += ["--symmetric", "--cipher-algo", config.cipher]
    args += ["--output", str(target)]
    result = _run(config.gpg_binary, args, input_bytes=text.encode("utf-8"))
    if result.returncode != 0:
        raise EncryptionError(_decode(result.stderr) or "encryption failed")
    return target


def decrypt_text(source: Path, config: Optional[EncryptionConfig] = None) -> str:
    """Decrypt a ``.gpg`` note. The passphrase prompt is delegated to gpg."""
    config = config or EncryptionConfig()
    result = _run(config.gpg_binary, ["--decrypt", str(source)])
    if result.returncode != 0:
        raise EncryptionError(_decode(result.stderr) or "decryption failed")
    return result.stdout.decode("utf-8", errors="replace")


def encrypt_file(path: Path, config: Optional[EncryptionConfig] = None, *, keep: bool = False) -> Path:
    """Encrypt an existing note in place, replacing it with ``<name>.gpg``."""
    config = config or EncryptionConfig()
    path = Path(path)
    if is_encrypted(path):
        return path
    text = path.read_text(encoding="utf-8", errors="replace")
    target = Path(str(path) + GPG_SUFFIX)
    encrypt_text(text, target, config)
    if not keep:
        path.unlink()
    return target


def decrypt_file(path: Path, config: Optional[EncryptionConfig] = None, *, keep: bool = False) -> Path:
    """Decrypt a ``.gpg`` note back into a plain ``.md`` file."""
    config = config or EncryptionConfig()
    path = Path(path)
    if not is_encrypted(path):
        return path
    text = decrypt_text(path, config)
    target = Path(str(path)[: -len(GPG_SUFFIX)])
    target.write_text(text, encoding="utf-8")
    if not keep:
        path.unlink()
    return target


def edit_encrypted(
    path: Path, editor: str, config: Optional[EncryptionConfig] = None
) -> bool:
    """Decrypt to a temp file, run ``$EDITOR`` on it, re-encrypt the result."""
    config = config or EncryptionConfig()
    text = decrypt_text(path, config)
    handle = tempfile.NamedTemporaryFile(
        "w", suffix=".md", prefix="tuinotes-", delete=False, encoding="utf-8"
    )
    try:
        handle.write(text)
        handle.close()
        os.chmod(handle.name, 0o600)
        result = subprocess.run([editor, handle.name], check=False)
        if result.returncode != 0:
            return False
        updated = Path(handle.name).read_text(encoding="utf-8", errors="replace")
    finally:
        try:
            os.unlink(handle.name)
        except OSError:  # pragma: no cover
            pass
    if updated == text:
        return False
    encrypt_text(updated, path, config)
    return True


def _decode(data: Optional[bytes]) -> str:
    return (data or b"").decode("utf-8", errors="replace").strip()
