import importlib
import os
from unittest.mock import MagicMock, patch

import pytest

import config
from handlers.google import auth as calendar_auth
from handlers.google import tasks_auth
from handlers.google import drive_auth as auth
from private_paths import PrivatePathError


@pytest.fixture
def files(tmp_path, monkeypatch):
    token = tmp_path / "fictional-drive.json"
    protected = {}
    for attr in ("GOOGLE_TOKEN_FILE", "GOOGLE_TASKS_TOKEN_FILE", "GOOGLE_CREDENTIALS_FILE"):
        path = tmp_path / (attr.lower() + ".json")
        path.write_text("fictional protected sentinel")
        protected[attr] = path
        monkeypatch.setattr(config, attr, path)
    monkeypatch.setattr(config, "GOOGLE_DRIVE_TOKEN_FILE", token)
    with patch.object(auth.Credentials, "from_authorized_user_file") as load, \
         patch.object(auth.InstalledAppFlow, "from_client_secrets_file") as flow:
        yield token, protected, load, flow
    assert all(p.read_text() == "fictional protected sentinel" for p in protected.values())
    assert calendar_auth.SCOPES == ["https://www.googleapis.com/auth/calendar.events.owned"]
    assert tasks_auth.SCOPES == ["https://www.googleapis.com/auth/tasks"]


def test_missing_token_never_implicitly_authorizes(files):
    token, _, load, flow = files
    with pytest.raises(auth.DriveAuthorizationRequired):
        auth.get_credentials()
    assert not token.exists()
    load.assert_not_called()
    flow.assert_not_called()


@pytest.mark.parametrize("interactive", [False, True])
@pytest.mark.parametrize("problem", ["malformed", "wrong_scopes", "invalid", "refresh_failed"])
def test_existing_bad_token_never_replaced_or_reconsented(files, interactive, problem):
    token, _, load, flow = files
    token.write_text("fictional drive sentinel")
    creds = load.return_value = MagicMock(valid=False, expired=False)
    creds.has_scopes.return_value = problem != "wrong_scopes"
    if problem == "malformed":
        load.side_effect = ValueError("PRIVATE_FICTIONAL_TOKEN")
    if problem == "refresh_failed":
        creds.expired = True
        creds.refresh_token = "fictional-refresh"
        creds.refresh.side_effect = RuntimeError("PRIVATE_FICTIONAL_REFRESH")
    with pytest.raises(auth.DriveAuthorizationRequired) as caught:
        auth.get_credentials(allow_interactive=interactive)
    assert "PRIVATE_FICTIONAL" not in str(caught.value)
    assert token.read_text() == "fictional drive sentinel"
    flow.assert_not_called()


def test_valid_token_is_reused_without_writes(files):
    token, _, load, flow = files
    token.write_text("fictional drive sentinel")
    load.return_value.valid = True
    assert auth.get_credentials() is load.return_value
    load.assert_called_once_with(str(token))
    assert token.read_text() == "fictional drive sentinel"
    flow.assert_not_called()


def test_explicit_setup_requests_only_drive_file_and_creates_new_file(files):
    token, protected, load, flow = files
    creds = flow.return_value.run_local_server.return_value
    creds.to_json.return_value = "fictional drive token"
    assert auth.get_credentials(allow_interactive=True) is creds
    assert auth.SCOPES == ["https://www.googleapis.com/auth/drive.file"]
    flow.assert_called_once_with(str(protected["GOOGLE_CREDENTIALS_FILE"]), auth.SCOPES)
    assert flow.return_value.run_local_server.call_args.kwargs["authorization_prompt_message"] == ""
    assert token.read_text() == "fictional drive token"
    load.assert_not_called()


@pytest.mark.parametrize("target", ["GOOGLE_TOKEN_FILE", "GOOGLE_TASKS_TOKEN_FILE", "GOOGLE_CREDENTIALS_FILE"])
def test_alias_of_protected_file_refused_before_read(files, monkeypatch, target):
    _, protected, load, flow = files
    monkeypatch.setattr(config, "GOOGLE_DRIVE_TOKEN_FILE", protected[target])
    with pytest.raises(auth.DriveAuthorizationRequired):
        auth.get_credentials(allow_interactive=True)
    load.assert_not_called()
    flow.assert_not_called()


@pytest.mark.parametrize("target", ["GOOGLE_TOKEN_FILE", "GOOGLE_TASKS_TOKEN_FILE", "GOOGLE_CREDENTIALS_FILE"])
def test_hardlink_alias_refused_before_loading_credentials(files, target):
    token, protected, load, flow = files
    os.link(protected[target], token)
    with pytest.raises(auth.DriveAuthorizationRequired):
        auth.get_credentials(allow_interactive=True)
    load.assert_not_called()
    flow.assert_not_called()


def test_private_path_guard_precedes_token_load(files):
    _, _, load, flow = files
    with patch.object(auth, "validate_private_paths", side_effect=PrivatePathError()):
        with pytest.raises(PrivatePathError):
            auth.get_credentials()
    load.assert_not_called()
    flow.assert_not_called()


def test_refresh_only_writes_drive_token_with_bounded_transport(files):
    token, _, load, flow = files
    token.write_text("fictional drive sentinel")
    creds = load.return_value = MagicMock(valid=False, expired=True, refresh_token="fictional-refresh")
    creds.to_json.return_value = "fictional refreshed drive token"

    def refresh(request):
        request(url="https://fictional.invalid/token", method="POST")
        creds.valid = True

    creds.refresh.side_effect = refresh
    with patch.object(auth, "Request") as request:
        auth.get_credentials()
    assert request.return_value.call_args.kwargs["timeout"] == 30
    assert token.read_text() == "fictional refreshed drive token"
    flow.assert_not_called()


def test_setup_cannot_overwrite_file_created_during_consent(files):
    token, _, _, flow = files
    creds = MagicMock(valid=True)

    def consent(**kwargs):
        token.write_text("fictional concurrently created sentinel")
        return creds

    flow.return_value.run_local_server.side_effect = consent
    with pytest.raises(auth.DriveAuthorizationRequired):
        auth.get_credentials(allow_interactive=True)
    assert token.read_text() == "fictional concurrently created sentinel"


def test_script_import_safe_and_explicit(capsys):
    with patch.object(auth, "get_credentials") as get:
        module = importlib.import_module("auth_drive")
        get.assert_not_called()
        assert module.main() == 0
        get.assert_called_once_with(allow_interactive=True)
    assert "PRIVATE_FICTIONAL" not in capsys.readouterr().out
