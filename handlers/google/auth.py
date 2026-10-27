from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

import config
from private_paths import validate_private_paths

SCOPES = [
    "https://www.googleapis.com/auth/calendar.events.owned",
]
HTTP_TIMEOUT_SECONDS = 30


class AuthorizationRequired(RuntimeError):
    def __init__(self):
        super().__init__(
            "Google Calendar authorization is required. "
            "Run python auth_google.py only when you explicitly choose to authorize."
        )


def get_credentials(*, allow_interactive: bool = False) -> Credentials:
    validate_private_paths([config.GOOGLE_CREDENTIALS_FILE, config.GOOGLE_TOKEN_FILE])
    token_path = config.GOOGLE_TOKEN_FILE
    creds: Credentials | None = None

    try:
        if token_path.exists():
            creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    except Exception:
        if not allow_interactive:
            raise AuthorizationRequired() from None

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                request = Request()

                def bounded_request(*args, **kwargs):
                    kwargs["timeout"] = HTTP_TIMEOUT_SECONDS
                    return request(*args, **kwargs)

                creds.refresh(bounded_request)
            except Exception:
                if not allow_interactive:
                    raise AuthorizationRequired() from None
                creds = None
        if creds is None or not creds.valid:
            if not allow_interactive:
                raise AuthorizationRequired()
            try:
                if not config.GOOGLE_CREDENTIALS_FILE.exists():
                    raise AuthorizationRequired()
                flow = InstalledAppFlow.from_client_secrets_file(
                    str(config.GOOGLE_CREDENTIALS_FILE), SCOPES
                )
                creds = flow.run_local_server(port=0)
            except Exception:
                raise AuthorizationRequired() from None

        try:
            token_path.parent.mkdir(parents=True, exist_ok=True)
            token_path.write_text(creds.to_json())
        except Exception:
            raise AuthorizationRequired() from None

    return creds
