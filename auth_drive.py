"""Explicit, import-safe Drive setup; creates a separate token only."""
import logging
import sys

from handlers.google.drive_auth import DriveAuthorizationRequired, get_credentials
from private_paths import PrivatePathError


def main() -> int:
    for name in ("google_auth_oauthlib", "oauthlib", "requests_oauthlib", "urllib3"):
        logging.getLogger(name).setLevel(logging.WARNING)
    print("Starting explicitly requested Google Drive authorization (separate token).")
    try:
        get_credentials(allow_interactive=True)
    except (DriveAuthorizationRequired, PrivatePathError) as exc:
        print(str(exc))
        return 1
    except Exception:
        print("Drive authorization failed. Check the local setup privately.")
        return 1
    print("Drive authorization ready. Existing Calendar/Tasks credentials and tokens were preserved.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
