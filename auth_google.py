"""
Run this script once to authorize Noah to access your Google Calendar.

    python auth_google.py

A browser window will open. Sign in, grant access, and the token will be
saved to GOOGLE_TOKEN_FILE (default token.json). After that, the bot reads the token
automatically and refreshes it when needed.
"""
import sys
from handlers.google.auth import AuthorizationRequired, get_credentials
from private_paths import PrivatePathError

def main() -> int:
    print("Starting explicitly requested Google authorization…")
    try:
        get_credentials(allow_interactive=True)
    except (AuthorizationRequired, PrivatePathError) as exc:
        print(str(exc))
        return 1
    except Exception:
        print("Google authorization failed. Check the local setup privately.")
        return 1
    print("Authorization complete.")
    return 0

if __name__ == "__main__":
    sys.exit(main())
