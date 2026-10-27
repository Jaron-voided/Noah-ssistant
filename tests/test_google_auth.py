from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
import importlib

import pytest

from handlers.google import auth


@pytest.fixture
def auth_files(monkeypatch):
    token, client = MagicMock(spec=Path), MagicMock(spec=Path)
    token.exists.return_value = False
    client.exists.return_value = True
    monkeypatch.setattr(auth.config, "GOOGLE_TOKEN_FILE", token)
    monkeypatch.setattr(auth.config, "GOOGLE_CREDENTIALS_FILE", client)
    with patch.object(auth.Credentials, "from_authorized_user_file") as load, \
         patch.object(auth.InstalledAppFlow, "from_client_secrets_file") as flow, \
         patch.object(auth, "validate_private_paths"):
        yield token, client, load, flow


@pytest.mark.parametrize("condition", ["missing", "unusable", "malformed", "refresh_failed"])
def test_normal_operations_never_start_interactive_oauth(condition, auth_files):
    token, client, load, flow = auth_files
    if condition != "missing":
        token.exists.return_value = True
        load.return_value = MagicMock(valid=False, expired=False)
    if condition == "malformed":
        load.side_effect = ValueError("PRIVATE_TOKEN_DETAIL")
    if condition == "refresh_failed":
        load.return_value.expired = True
        load.return_value.refresh_token = "fictional-test-refresh"
        load.return_value.refresh.side_effect = RuntimeError("PRIVATE_REFRESH_DETAIL")
    with pytest.raises(auth.AuthorizationRequired) as caught:
        auth.get_credentials()
    assert "authorization" in str(caught.value).lower()
    assert "PRIVATE" not in str(caught.value)
    flow.assert_not_called()
    token.write_text.assert_not_called()
    token.parent.mkdir.assert_not_called()


def test_valid_existing_credentials_are_reused_without_write(auth_files):
    token, client, load, flow = auth_files
    token.exists.return_value = True
    load.return_value.valid = True
    assert auth.get_credentials() is load.return_value
    flow.assert_not_called()
    token.write_text.assert_not_called()


def test_refresh_preserves_scope_and_path_without_interactive_flow(auth_files):
    token, client, load, flow = auth_files
    token.exists.return_value = True
    load.return_value = MagicMock(valid=False, expired=True, refresh_token="fictional-test-refresh")
    load.return_value.to_json.return_value = "{}"
    load.return_value.refresh.side_effect = lambda request: setattr(load.return_value, "valid", True)
    assert auth.get_credentials() is load.return_value
    load.assert_called_once_with(str(token), auth.SCOPES)
    load.return_value.refresh.assert_called_once()
    flow.assert_not_called()
    token.write_text.assert_called_once_with("{}")
    assert auth.SCOPES == ["https://www.googleapis.com/auth/calendar.events.owned"]


def test_explicit_setup_can_authorize_at_existing_path(auth_files):
    token, client, load, flow = auth_files
    flow.return_value.run_local_server.return_value.to_json.return_value = "{}"
    auth.get_credentials(allow_interactive=True)
    flow.assert_called_once_with(str(client), auth.SCOPES)
    flow.return_value.run_local_server.assert_called_once_with(port=0)
    token.write_text.assert_called_once_with("{}")


def test_setup_script_is_import_safe_and_explicit(capsys):
    with patch.object(auth, "get_credentials") as get:
        module = importlib.import_module("auth_google")
        get.assert_not_called()
        assert module.main() == 0
        get.assert_called_once_with(allow_interactive=True)
    assert "PRIVATE" not in capsys.readouterr().out


def test_unsafe_configured_private_paths_stop_before_token_read(auth_files):
    from private_paths import PrivatePathError

    token, client, load, flow = auth_files
    with patch.object(auth, "validate_private_paths", side_effect=PrivatePathError()) as check:
        with pytest.raises(PrivatePathError):
            auth.get_credentials()
    check.assert_called_once_with([client, token])
    token.exists.assert_not_called()
    load.assert_not_called()
    flow.assert_not_called()


def test_existing_grant_refresh_has_a_bounded_request(auth_files):
    token, client, load, flow = auth_files
    token.exists.return_value = True
    creds = load.return_value = MagicMock(valid=False, expired=True, refresh_token="fictional-test-refresh")

    def refresh(request):
        request(url="https://fictional.invalid/token", method="POST")
        creds.valid = True

    creds.refresh.side_effect = refresh
    with patch.object(auth, "Request") as request:
        auth.get_credentials()
    assert request.return_value.call_args.kwargs["timeout"] == 30
    flow.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["read", "add"])
async def test_authorization_requirement_is_clear_in_bot_reply(operation):
    import config
    from handlers import query
    from handlers.calendar_confirm import handle_callback

    update, context = MagicMock(), MagicMock()
    update.effective_user.id = config.TELEGRAM_USER_ID
    update.message.reply_text = AsyncMock()
    update.callback_query.data = "cal_add:1"
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_text = AsyncMock()
    context.user_data = {}
    context.application.bot_data = {"pending_cal_1": {
        "title": "Fictional event", "event_dt": "2027-01-15T17:00:00-05:00"
    }}
    target = "events_for_range" if operation == "read" else "create_event"
    with patch("handlers.google.calendar." + target, side_effect=auth.AuthorizationRequired()):
        if operation == "read":
            await query._calendar_query(update, context, "2027-01-15")
            response = update.message.reply_text.call_args.args[0]
        else:
            await handle_callback(update, context)
            response = update.callback_query.edit_message_text.call_args.args[0]
    assert "authorization is required" in response
    assert "auth_google.py" in response
