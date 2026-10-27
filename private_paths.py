"""Check private-path Git metadata without opening the private files."""
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parent


class PrivatePathError(RuntimeError):
    def __init__(self):
        super().__init__(
            "Private files inside the repository must be Git-ignored and untracked. "
            "Check the private-path Git exclusions before continuing."
        )


def validate_private_paths(paths) -> None:
    if not (ROOT / ".git").exists():
        return  # An exported copy has no Git index to disclose files through.
    try:
        for path in paths:
            path = Path(path)
            # Check both a possible in-repository symlink and its resolved target.
            for candidate in {path.absolute(), path.resolve()}:
                if not candidate.is_relative_to(ROOT):
                    continue
                relative = candidate.relative_to(ROOT).as_posix()
                ignored = subprocess.run(
                    ["git", "check-ignore", "--no-index", "--quiet", "--", relative],
                    cwd=ROOT, capture_output=True, timeout=5,
                )
                indexed = subprocess.run(
                    ["git", "ls-files", "--error-unmatch", "--", relative],
                    cwd=ROOT, capture_output=True, timeout=5,
                )
                if ignored.returncode != 0 or indexed.returncode != 1:
                    raise PrivatePathError()
    except Exception:
        raise PrivatePathError() from None
