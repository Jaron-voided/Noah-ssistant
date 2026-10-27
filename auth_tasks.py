"""Explicit, import-safe Tasks setup. Never run automatically from the bot."""
import logging
import sys

from handlers.google.tasks_auth import TasksAuthorizationRequired, get_credentials
from private_paths import PrivatePathError


def main() -> int:
    # The OAuth callback URL contains a code; suppress transport/flow logging.
    for name in ("google_auth_oauthlib", "oauthlib", "requests_oauthlib", "urllib3"):
        logging.getLogger(name).setLevel(logging.WARNING)
    print("Starting explicitly requested Google Tasks authorization (separate token).")
    try:
        get_credentials(allow_interactive=True)
    except (TasksAuthorizationRequired, PrivatePathError) as exc:
        print(str(exc))
        return 1
    except Exception:
        print("Tasks authorization failed. Check the local setup privately.")
        return 1
    print("Tasks authorization ready. Calendar credentials and token were preserved.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
