"""Save supplied text in app-created folders; never fetch URLs or share files."""
from io import BytesIO
import re

import httplib2
from google_auth_httplib2 import AuthorizedHttp
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

from handlers.google.auth import HTTP_TIMEOUT_SECONDS
from handlers.google.drive_auth import get_credentials

FOLDER_MIME = "application/vnd.google-apps.folder"


def _service():
    transport = AuthorizedHttp(get_credentials(), http=httplib2.Http(timeout=HTTP_TIMEOUT_SECONDS))
    return build("drive", "v3", http=transport, cache_discovery=False)


def _folder(files, role, name, parent="root"):
    if not re.fullmatch(r"[A-Za-z0-9_-]+", parent):
        raise RuntimeError("Invalid Drive folder metadata.")
    # Fixed roles/names only. Never interpolate Telegram content into Drive queries.
    query = (f"trashed = false and name = '{name}' and mimeType = '{FOLDER_MIME}' and '{parent}' in parents "
             f"and 'me' in owners and appProperties has {{ key='noah_folder' and value='{role}' }}")
    params = dict(q=query, spaces="drive", pageSize=2, fields="files(id),nextPageToken")
    found, seen = [], set()
    while True:
        result = files.list(**params).execute(num_retries=0)
        found.extend(result.get("files", []))
        marker = result.get("nextPageToken")
        if len(found) > 1 or not marker:
            break
        if not isinstance(marker, str) or marker in seen:
            raise RuntimeError("Invalid Drive pagination metadata.")
        seen.add(marker)
        params["pageToken"] = marker
    if len(found) > 1:
        raise RuntimeError("Multiple Noah folders need private inspection.")
    if found:
        folder_id = found[0]["id"]
    else:
        folder_id = files.create(body={
            "name": name, "mimeType": FOLDER_MIME, "parents": [parent],
            "appProperties": {"noah_folder": role},
        }, fields="id").execute(num_retries=0)["id"]
    if not isinstance(folder_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", folder_id):
        raise RuntimeError("Invalid Drive folder metadata.")
    return folder_id


def save_text(*, name: str, content: str, category: str) -> dict:
    if category not in ("Links", "Notes") or not name or not content:
        raise ValueError("Invalid Drive capture.")
    files = _service().files()
    root = _folder(files, "inbox", "Noah Inbox")
    parent = _folder(files, category.lower(), category, root)
    media = MediaIoBaseUpload(BytesIO(content.encode("utf-8")), mimetype="text/plain", resumable=False)
    # Confirmed action may create the folders and this new file. Never update/share.
    result = files.create(
        body={"name": name, "mimeType": "text/plain", "parents": [parent]},
        media_body=media, fields="id",
    ).execute(num_retries=0)
    if not isinstance(result.get("id"), str) or not result["id"]:
        raise RuntimeError("Missing Drive creation result.")
    return result


def save_photo(*, name: str, content: bytes, category: str | None, caption: str = "") -> dict:
    if not name or not content or len(content) > 10 * 1024 * 1024:
        raise ValueError("Invalid photo upload.")
    if category is not None and not re.fullmatch(r"[a-z][a-z0-9_-]{0,23}", category):
        raise ValueError("Invalid image category.")
    files = _service().files()
    root = _folder(files, "inbox", "Noah Inbox")
    parent = _folder(files, "images", "Images", root)
    if category:
        parent = _folder(files, "image_" + category, category, parent)
    media = MediaIoBaseUpload(BytesIO(content), mimetype="image/jpeg", resumable=False)
    result = files.create(body={"name": name, "mimeType": "image/jpeg", "parents": [parent],
                                "description": caption}, media_body=media, fields="id").execute(num_retries=0)
    if not isinstance(result.get("id"), str) or not result["id"]:
        raise RuntimeError("Missing Drive photo creation result.")
    return result
