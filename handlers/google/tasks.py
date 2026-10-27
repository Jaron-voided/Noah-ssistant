"""Small Google Tasks adapter: default list, confirmed insert, open-task reads."""
import httplib2
from google_auth_httplib2 import AuthorizedHttp
from googleapiclient.discovery import build

from handlers.google.auth import HTTP_TIMEOUT_SECONDS
from handlers.google.tasks_auth import get_credentials

TASKLIST = "@default"


def _service():
    transport = AuthorizedHttp(get_credentials(), http=httplib2.Http(timeout=HTTP_TIMEOUT_SECONDS))
    return build("tasks", "v1", http=transport, cache_discovery=False)


def create_task(title: str, notes: str) -> dict:
    if not title.strip() or len(title) > 1024 or len(notes) > 8192:
        raise ValueError("Task title or notes exceed the supported size.")
    # No retries: an interrupted insertion may have succeeded remotely.
    return _service().tasks().insert(
        tasklist=TASKLIST, body={"title": title, "notes": notes},
    ).execute(num_retries=0)


def list_open_tasks(limit: int = 20) -> tuple[list[dict], bool]:
    """Return at most limit open tasks and whether more exist, fetching as needed."""
    api = _service().tasks()
    params = dict(tasklist=TASKLIST, showCompleted=False, showDeleted=False,
                  showHidden=False, maxResults=100)
    found, seen = [], set()
    while True:
        page = api.list(**params).execute(num_retries=0)
        found.extend(t for t in page.get("items", [])
                     if not t.get("deleted") and not t.get("hidden") and t.get("status") == "needsAction")
        marker = page.get("nextPageToken")
        if len(found) > limit or not marker:
            return found[:limit], len(found) > limit
        if not isinstance(marker, str) or marker in seen:
            raise RuntimeError("Invalid Tasks pagination metadata.")
        seen.add(marker)
        params["pageToken"] = marker
