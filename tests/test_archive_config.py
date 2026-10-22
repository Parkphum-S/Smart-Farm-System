from app.core.config import Settings


def test_archive_path_defaults_to_ssd_archive_directory():
    settings = Settings(_env_file=None)

    assert settings.archive_path == "/mnt/smartfarm-data/archive"


def test_archive_path_can_be_overridden():
    settings = Settings(
        _env_file=None,
        archive_path="/tmp/smartfarm-archive-test",
    )

    assert settings.archive_path == "/tmp/smartfarm-archive-test"
