"""Explicit Drive-file consent isolated from Calendar/Tasks token storage."""
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

import config
from handlers.google.auth import HTTP_TIMEOUT_SECONDS
from private_paths import validate_private_paths

SCOPES = ["https://www.googleapis.com/auth/drive.file"]


class DriveAuthorizationRequired(RuntimeError):
    def __init__(self):
        super().__init__(
            "Google Drive authorization is required. Enable the Google Drive API, "
            "then explicitly run python auth_drive.py. Existing Calendar/Tasks settings "
            "were preserved. Existing token files will not be replaced by setup."
        )


def _separate_token() -> Path:
    token = Path(config.GOOGLE_DRIVE_TOKEN_FILE)
    for original in (config.GOOGLE_TOKEN_FILE, config.GOOGLE_TASKS_TOKEN_FILE,
                     config.GOOGLE_CREDENTIALS_FILE):
        original = Path(original)
        if token.resolve() == original.resolve() or (
            token.exists() and original.exists() and token.samefile(original)
        ):
            raise DriveAuthorizationRequired()
    validate_private_paths([config.GOOGLE_CREDENTIALS_FILE, token])
    return token


def get_credentials(*, allow_interactive=False) -> Credentials:
    token = _separate_token()
    try:
        if token.exists():
            creds = Credentials.from_authorized_user_file(str(token))
            if not creds.has_scopes(SCOPES):
                raise DriveAuthorizationRequired()
            if not creds.valid:
                if not creds.expired or not creds.refresh_token:
                    raise DriveAuthorizationRequired()
                request = Request()

                def bounded_request(*args, **kwargs):
                    kwargs["timeout"] = HTTP_TIMEOUT_SECONDS
                    return request(*args, **kwargs)

                creds.refresh(bounded_request)
                if not creds.valid:
                    raise DriveAuthorizationRequired()
                token.write_text(creds.to_json(), encoding="utf-8")
            return creds
        if not allow_interactive:
            raise DriveAuthorizationRequired()
        flow = InstalledAppFlow.from_client_secrets_file(str(config.GOOGLE_CREDENTIALS_FILE), SCOPES)
        creds = flow.run_local_server(
            port=0, authorization_prompt_message="", success_message="Drive authorization complete. You can close this window.",
            access_type="offline", prompt="consent",
        )
        if not creds.valid or not creds.has_scopes(SCOPES):
            raise DriveAuthorizationRequired()
        token.parent.mkdir(parents=True, exist_ok=True)
        with token.open("x", encoding="utf-8") as stream:
            stream.write(creds.to_json())
        return creds
    except Exception:
        raise DriveAuthorizationRequired() from None
