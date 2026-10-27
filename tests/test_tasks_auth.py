import importlib
import os
from unittest.mock import MagicMock, patch

import pytest

import config
from handlers.google import auth as calendar_auth
from handlers.google import tasks_auth as auth
from private_paths import PrivatePathError


@pytest.fixture
def files(tmp_path, monkeypatch):
    token = tmp_path / "fictional-tasks.json"
    calendar = tmp_path / "fictional-calendar.json"
    client = tmp_path / "fictional-client.json"
    # These are fictional sentinels, never real credential files.
    calendar.write_text("fictional calendar sentinel")
    client.write_text("fictional client sentinel")
    monkeypatch.setattr(config, "GOOGLE_TASKS_TOKEN_FILE", token)
    monkeypatch.setattr(config, "GOOGLE_TOKEN_FILE", calendar)
    monkeypatch.setattr(config, "GOOGLE_CREDENTIALS_FILE", client)
    with patch.object(auth.Credentials, "from_authorized_user_file") as load, \
         patch.object(auth.InstalledAppFlow, "from_client_secrets_file") as flow:
        yield token, calendar, client, load, flow
    assert calendar.read_text() == "fictional calendar sentinel"
    assert client.read_text() == "fictional client sentinel"
    assert calendar_auth.SCOPES == ["https://www.googleapis.com/auth/calendar.events.owned"]


def test_missing_tasks_token_never_interactively_authorizes(files):
    token, _, _, load, flow = files
    with pytest.raises(auth.TasksAuthorizationRequired):
        auth.get_credentials()
    flow.assert_not_called()
    load.assert_not_called()
    assert not token.exists()


@pytest.mark.parametrize("interactive", [False, True])
@pytest.mark.parametrize("problem", ["malformed", "wrong_scopes", "invalid", "refresh_failed"])
def test_existing_unusable_tasks_token_is_never_replaced_or_reconsented(files, interactive, problem):
    token, _, _, load, flow = files
    token.write_text("fictional tasks sentinel")
    creds = load.return_value = MagicMock(valid=False, expired=False)
    creds.has_scopes.return_value = problem != "wrong_scopes"
    if problem == "malformed":
        load.side_effect = ValueError("PRIVATE_FICTIONAL_TOKEN")
    if problem == "refresh_failed":
        creds.expired = True
        creds.refresh_token = "fictional-refresh"
        creds.refresh.side_effect = RuntimeError("PRIVATE_FICTIONAL_REFRESH")
    with pytest.raises(auth.TasksAuthorizationRequired) as caught:
        auth.get_credentials(allow_interactive=interactive)
    assert "PRIVATE_FICTIONAL" not in str(caught.value)
    assert token.read_text() == "fictional tasks sentinel"
    flow.assert_not_called()


def test_valid_tasks_token_reused_without_write(files):
    token, _, _, load, flow = files
    token.write_text("fictional tasks sentinel")
    load.return_value.valid = True
    load.return_value.has_scopes.return_value = True
    assert auth.get_credentials() is load.return_value
    load.assert_called_once_with(str(token))
    assert token.read_text() == "fictional tasks sentinel"
    flow.assert_not_called()


def test_explicit_setup_requests_only_tasks_and_writes_only_new_tasks_file(files):
    token, _, client, load, flow = files
    creds = flow.return_value.run_local_server.return_value
    creds.valid = True
    creds.has_scopes.return_value = True
    creds.to_json.return_value = "fictional new tasks token"
    auth.get_credentials(allow_interactive=True)
    assert auth.SCOPES == ["https://www.googleapis.com/auth/tasks"]
    flow.assert_called_once_with(str(client), auth.SCOPES)
    assert flow.return_value.run_local_server.call_args.kwargs["authorization_prompt_message"] == ""
    assert token.read_text() == "fictional new tasks token"
    load.assert_not_called()


@pytest.mark.parametrize("target", ["calendar", "client", "drive"])
def test_tasks_token_cannot_alias_protected_paths(files, monkeypatch, target):
    token, calendar, client, load, flow = files
    drive = token.parent / "fictional-drive.json"
    monkeypatch.setattr(config, "GOOGLE_DRIVE_TOKEN_FILE", drive)
    targets = {"calendar": calendar, "client": client, "drive": drive}
    monkeypatch.setattr(config, "GOOGLE_TASKS_TOKEN_FILE", targets[target])
    with pytest.raises(auth.TasksAuthorizationRequired):
        auth.get_credentials(allow_interactive=True)
    load.assert_not_called()
    flow.assert_not_called()


def test_private_path_rejected_before_token_loading(files):
    _, _, _, load, flow = files
    with patch.object(auth, "validate_private_paths", side_effect=PrivatePathError()):
        with pytest.raises(PrivatePathError):
            auth.get_credentials()
    load.assert_not_called()
    flow.assert_not_called()


def test_hardlink_to_calendar_token_refused_before_loading(files):
    token, calendar, _, load, flow = files
    os.link(calendar, token)
    with pytest.raises(auth.TasksAuthorizationRequired):
        auth.get_credentials(allow_interactive=True)
    load.assert_not_called()
    flow.assert_not_called()


def test_refresh_is_bounded_and_writes_only_tasks_file(files):
    token, _, _, load, flow = files
    token.write_text("fictional tasks sentinel")
    creds = load.return_value = MagicMock(valid=False, expired=True, refresh_token="fictional-refresh")
    creds.to_json.return_value = "fictional refreshed tasks token"

    def refresh(request):
        request(url="https://fictional.invalid/token", method="POST")
        creds.valid = True

    creds.refresh.side_effect = refresh
    with patch.object(auth, "Request") as request:
        auth.get_credentials()
    assert request.return_value.call_args.kwargs["timeout"] == 30
    assert token.read_text() == "fictional refreshed tasks token"
    flow.assert_not_called()


def test_script_import_safe_and_explicit(capsys):
    with patch.object(auth, "get_credentials") as get:
        module = importlib.import_module("auth_tasks")
        get.assert_not_called()
        assert module.main() == 0
        get.assert_called_once_with(allow_interactive=True)
    assert "PRIVATE_FICTIONAL" not in capsys.readouterr().out


def test_setup_race_does_not_overwrite_newly_existing_file(files):
    token, _, _, _, flow = files
    creds = MagicMock(valid=True)
    creds.to_json.return_value = "fictional new token"

    def consent(**kwargs):
        token.write_text("fictional concurrently created sentinel")
        return creds

    flow.return_value.run_local_server.side_effect = consent
    with pytest.raises(auth.TasksAuthorizationRequired):
        auth.get_credentials(allow_interactive=True)
    assert token.read_text() == "fictional concurrently created sentinel"
