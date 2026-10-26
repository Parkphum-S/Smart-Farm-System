"""Safe helpers for installing and verifying local secret files."""

from __future__ import annotations

import os
import shutil
import stat
import tempfile
from pathlib import Path
from typing import Callable


class SecretRecoveryRequired(RuntimeError):
    """An operation failed and manual recovery is required."""

    def __init__(self, message: str, recovery_path: Path | None = None):
        super().__init__(message)
        self.recovery_path = recovery_path


def fsync_directory(directory: Path) -> None:
    """Persist directory-entry changes where supported."""
    fd = os.open(str(directory), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def create_secret_backup(target: Path) -> Path:
    """Create a private, durable backup beside an existing secret file."""
    if not target.is_file():
        raise FileNotFoundError("secret file does not exist")

    fd, name = tempfile.mkstemp(
        prefix=f".{target.name}.recovery.",
        dir=str(target.parent),
    )
    backup = Path(name)

    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as output:
            with target.open("rb") as source:
                shutil.copyfileobj(source, output)
            output.flush()
            os.fsync(output.fileno())

        if stat.S_IMODE(backup.stat().st_mode) != 0o600:
            raise OSError("recovery file permissions are incorrect")

        fsync_directory(target.parent)
        return backup
    except BaseException:
        try:
            backup.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def install_prepared_secret(prepared: Path, target: Path) -> Path:
    """Install a prepared file while retaining the previous file for recovery.

    The caller must verify the installed file and explicitly remove the returned
    backup only after all post-install checks have passed.
    """
    backup = create_secret_backup(target)

    try:
        os.replace(prepared, target)
    except OSError as exc:
        raise SecretRecoveryRequired(
            "secret replacement failed; inspect database state before retrying",
            backup,
        ) from exc

    try:
        fsync_directory(target.parent)
    except OSError as exc:
        raise SecretRecoveryRequired(
            "directory sync failed after replacement; manual recovery required",
            backup,
        ) from exc

    return backup


def verify_secret_file(
    path: Path,
    expected_hash: str,
    hash_token: Callable[[str], str],
) -> bool:
    """Check permissions and token/hash correspondence without displaying secrets."""
    if not path.is_file():
        return False

    try:
        if stat.S_IMODE(path.stat().st_mode) != 0o600:
            return False

        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return False

    import re

    matches = [
        line for line in content.splitlines()
        if re.match(r"^\s*#\s*define\s+DEVICE_API_KEY\b", line)
    ]
    if len(matches) != 1:
        return False

    match = re.fullmatch(
        r'\s*#\s*define\s+DEVICE_API_KEY\s+"([^"]*)"\s*',
        matches[0],
    )
    if not match:
        return False

    try:
        return hash_token(match.group(1)) == expected_hash
    except (TypeError, ValueError):
        return False
