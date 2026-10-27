from pathlib import Path
import subprocess
from unittest.mock import patch

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("name", [
    "google_token.json", "noah.db-journal", "noah.sqlite-journal", "noah.sqlite-wal",
    "noah.sqlite-shm", "noah.sqlite3-journal", "noah.sqlite3-wal", "noah.sqlite3-shm",
])
def test_private_filename_patterns_are_ignored(name):
    result = subprocess.run(["git", "check-ignore", "--no-index", "--quiet", "--", name],
                            cwd=ROOT, capture_output=True)
    assert result.returncode == 0


def test_unignored_override_is_rejected_without_reading_or_creating_it():
    from private_paths import PrivatePathError, validate_private_paths

    path = ROOT / "fictional-unignored-private-file.json"
    with patch.object(Path, "open", side_effect=AssertionError("Content access forbidden")):
        with pytest.raises(PrivatePathError) as caught:
            validate_private_paths([path])
    assert path.name not in str(caught.value)


def test_private_paths_outside_repository_need_no_git_exclusion(tmp_path):
    from private_paths import validate_private_paths

    with patch("private_paths.subprocess.run") as run:
        validate_private_paths([tmp_path / "fictional-secret.json"])
    run.assert_not_called()


def test_ignored_but_indexed_private_file_is_rejected():
    from private_paths import PrivatePathError, validate_private_paths

    with patch("private_paths.subprocess.run") as run:
        run.return_value.returncode = 0  # both ignored and indexed
        with pytest.raises(PrivatePathError):
            validate_private_paths([ROOT / "token.json"])


def test_db_and_sidecars_are_checked_before_database_open(tmp_path, monkeypatch):
    import config
    from db import store
    from private_paths import PrivatePathError

    monkeypatch.setattr(config, "DB_PATH", tmp_path / "fictional.custom")
    with patch("db.store.validate_private_paths", side_effect=PrivatePathError()) as check, \
         patch("db.store.sqlite3.connect") as connect:
        with pytest.raises(PrivatePathError):
            store.init_db()
    connect.assert_not_called()
    checked = check.call_args.args[0]
    assert {path.name for path in checked} == {
        "fictional.custom", "fictional.custom-journal", "fictional.custom-wal", "fictional.custom-shm"
    }
