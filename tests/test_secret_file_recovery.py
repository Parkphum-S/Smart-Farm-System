import os
from pathlib import Path

import pytest

from app.security.secret_file_recovery import (
    SecretRecoveryRequired,
    create_secret_backup,
    install_prepared_secret,
    verify_secret_file,
)


def test_backup_preserves_original_and_is_private(tmp_path):
    target = tmp_path / "secrets.h"
    target.write_text('#define DEVICE_API_KEY "old-placeholder"\n')
    target.chmod(0o600)

    backup = create_secret_backup(target)

    assert backup.read_bytes() == target.read_bytes()
    assert backup.stat().st_mode & 0o777 == 0o600
    assert target.read_text().endswith('"old-placeholder"\n')


def test_install_keeps_backup_until_caller_verifies(tmp_path):
    target = tmp_path / "secrets.h"
    prepared = tmp_path / ".prepared"
    target.write_text('#define DEVICE_API_KEY "old-placeholder"\n')
    target.chmod(0o600)
    prepared.write_text('#define DEVICE_API_KEY "new-placeholder"\n')
    prepared.chmod(0o600)

    backup = install_prepared_secret(prepared, target)

    assert target.read_text().endswith('"new-placeholder"\n')
    assert backup.read_text().endswith('"old-placeholder"\n')
    assert backup.stat().st_mode & 0o777 == 0o600
    assert not prepared.exists()


def test_replace_failure_retains_backup_and_original(tmp_path, monkeypatch):
    target = tmp_path / "secrets.h"
    prepared = tmp_path / ".prepared"
    target.write_text('#define DEVICE_API_KEY "old-placeholder"\n')
    target.chmod(0o600)
    prepared.write_text('#define DEVICE_API_KEY "new-placeholder"\n')
    prepared.chmod(0o600)

    def fail_replace(source, destination):
        raise OSError("simulated replace failure")

    monkeypatch.setattr(os, "replace", fail_replace)

    with pytest.raises(SecretRecoveryRequired) as caught:
        install_prepared_secret(prepared, target)

    backup = caught.value.recovery_path
    assert backup is not None and backup.exists()
    assert backup.read_text().endswith('"old-placeholder"\n')
    assert target.read_text().endswith('"old-placeholder"\n')
    assert prepared.exists()


def test_verification_checks_hash_and_file_mode(tmp_path):
    target = tmp_path / "secrets.h"
    target.write_text('#define DEVICE_API_KEY "test-placeholder"\n')
    target.chmod(0o600)

    def fake_hash(token):
        return "expected-hash" if token == "test-placeholder" else "wrong-hash"

    assert verify_secret_file(target, "expected-hash", fake_hash)
    assert not verify_secret_file(target, "other-hash", fake_hash)

    target.chmod(0o644)
    assert not verify_secret_file(target, "expected-hash", fake_hash)


def test_verification_rejects_duplicate_key_definitions(tmp_path):
    target = tmp_path / "secrets.h"
    target.write_text(
        '#define DEVICE_API_KEY "first-placeholder"\n'
        '#define DEVICE_API_KEY "second-placeholder"\n'
    )
    target.chmod(0o600)

    assert not verify_secret_file(target, "expected-hash", lambda _: "expected-hash")


def test_directory_fsync_failure_retains_backup(tmp_path, monkeypatch):
    import app.security.secret_file_recovery as recovery

    target = tmp_path / "secrets.h"
    prepared = tmp_path / ".prepared"
    target.write_text('#define DEVICE_API_KEY "old-placeholder"\n')
    target.chmod(0o600)
    prepared.write_text('#define DEVICE_API_KEY "new-placeholder"\n')
    prepared.chmod(0o600)

    real_fsync_directory = recovery.fsync_directory
    calls = {"count": 0}

    def fail_second_directory_sync(directory):
        calls["count"] += 1
        if calls["count"] == 2:
            raise OSError("simulated directory fsync failure")
        return real_fsync_directory(directory)

    monkeypatch.setattr(
        recovery, "fsync_directory", fail_second_directory_sync
    )

    with pytest.raises(SecretRecoveryRequired) as caught:
        install_prepared_secret(prepared, target)

    backup = caught.value.recovery_path
    assert backup is not None and backup.exists()
    assert backup.read_text().endswith('"old-placeholder"\n')
    assert target.read_text().endswith('"new-placeholder"\n')


def test_failed_verification_does_not_delete_recovery_backup(tmp_path):
    target = tmp_path / "secrets.h"
    prepared = tmp_path / ".prepared"
    target.write_text('#define DEVICE_API_KEY "old-placeholder"\n')
    target.chmod(0o600)
    prepared.write_text('#define DEVICE_API_KEY "new-placeholder"\n')
    prepared.chmod(0o600)

    backup = install_prepared_secret(prepared, target)

    # The caller must retain the backup when post-install verification fails.
    assert not verify_secret_file(target, "not-the-expected-hash", lambda _: "different")
    assert backup.exists()
    assert backup.read_text().endswith('"old-placeholder"\n')


def test_backup_creation_failure_does_not_replace_original(
    tmp_path, monkeypatch
):
    import app.security.secret_file_recovery as recovery

    target = tmp_path / "secrets.h"
    prepared = tmp_path / ".prepared"
    original_content = '#define DEVICE_API_KEY "old-placeholder"\n'

    target.write_text(original_content)
    target.chmod(0o600)
    prepared.write_text('#define DEVICE_API_KEY "new-placeholder"\n')
    prepared.chmod(0o600)

    def fail_backup(_target):
        raise OSError("simulated backup creation failure")

    monkeypatch.setattr(recovery, "create_secret_backup", fail_backup)

    with pytest.raises(OSError, match="simulated backup creation failure"):
        install_prepared_secret(prepared, target)

    assert target.read_text() == original_content
    assert target.stat().st_mode & 0o777 == 0o600
    assert prepared.exists()
    assert prepared.read_text() == '#define DEVICE_API_KEY "new-placeholder"\n'
