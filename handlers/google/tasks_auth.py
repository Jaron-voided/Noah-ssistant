"""Separate Tasks consent and storage; never repurpose the Calendar token."""
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

import config
from handlers.google.auth import HTTP_TIMEOUT_SECONDS
from private_paths import validate_private_paths

SCOPES = ["https://www.googleapis.com/auth/tasks"]


class TasksAuthorizationRequired(RuntimeError):
    def __init__(self):
        super().__init__(
            "Google Tasks authorization is required. Enable the Google Tasks API, "
            "then explicitly run python auth_tasks.py. Calendar settings were preserved. "
            "Existing token files will not be replaced by setup."
        )


def _separate_token() -> Path:
    token = Path(config.GOOGLE_TASKS_TOKEN_FILE)
    protected = [config.GOOGLE_TOKEN_FILE, config.GOOGLE_DRIVE_TOKEN_FILE,
                 config.GOOGLE_CREDENTIALS_FILE]
    for original in protected:
        original = Path(original)
        if token.resolve() == original.resolve() or (
            token.exists() and original.exists() and token.samefile(original)
        ):
            raise TasksAuthorizationRequired()
    validate_private_paths([config.GOOGLE_CREDENTIALS_FILE, token])
    return token


def get_credentials(*, allow_interactive=False) -> Credentials:
    token = _separate_token()
    try:
        if token.exists():
            # Do not pass scopes to the loader: verify what this token records.
            creds = Credentials.from_authorized_user_file(str(token))
            if not creds.has_scopes(SCOPES):
                raise TasksAuthorizationRequired()
            if not creds.valid:
                if not creds.expired or not creds.refresh_token:
                    raise TasksAuthorizationRequired()
                request = Request()

                def bounded_request(*args, **kwargs):
                    kwargs["timeout"] = HTTP_TIMEOUT_SECONDS
                    return request(*args, **kwargs)

                creds.refresh(bounded_request)
                if not creds.valid:
                    raise TasksAuthorizationRequired()
                token.write_text(creds.to_json(), encoding="utf-8")
            return creds
        if not allow_interactive:
            raise TasksAuthorizationRequired()
        flow = InstalledAppFlow.from_client_secrets_file(
            str(config.GOOGLE_CREDENTIALS_FILE), SCOPES,
        )
        # Do not print authorization URLs, state or callback details.
        creds = flow.run_local_server(
            port=0, authorization_prompt_message="", success_message="Tasks authorization complete. You can close this window.",
            access_type="offline", prompt="consent",
        )
        if not creds.valid or not creds.has_scopes(SCOPES):
            raise TasksAuthorizationRequired()
        token.parent.mkdir(parents=True, exist_ok=True)
        # Exclusive creation: setup cannot replace any existing file.
        with token.open("x", encoding="utf-8") as stream:
            stream.write(creds.to_json())
        return creds
    except Exception:
        raise TasksAuthorizationRequired() from None
