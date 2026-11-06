"""Google Drive access: OAuth (authorization code + PKCE), token storage and browsing."""

import base64
import hashlib
import json
import re
import secrets
import threading
import time
from collections.abc import Callable
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

from ..config import settings

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
API = "https://www.googleapis.com/drive/v3"
SCOPE = "https://www.googleapis.com/auth/drive.readonly"
FOLDER = "application/vnd.google-apps.folder"
_FIELDS = "id,name,mimeType,size,resourceKey"
_KIND_FILTER = f"(mimeType='{FOLDER}' or mimeType contains 'image/' or mimeType contains 'video/')"

_lock = threading.Lock()
_pending: dict[str, str] = {}  # OAuth state -> PKCE verifier


class DriveError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


class DownloadCancelled(Exception):
    pass


def _raise_if_cancelled(cancel_event: threading.Event | None) -> None:
    if cancel_event and cancel_event.is_set():
        raise DownloadCancelled("Google Drive download cancelled")


def configured() -> bool:
    return bool(settings.google_client_id and settings.google_client_secret)


def _token_path():
    return settings.storage_dir / "google_token.json"


def _load() -> dict | None:
    try:
        return json.loads(_token_path().read_text("utf-8"))
    except (OSError, ValueError):
        return None


def _save(tok: dict) -> None:
    settings.storage_dir.mkdir(parents=True, exist_ok=True)
    _token_path().write_text(json.dumps(tok), "utf-8")


def _require_configured() -> None:
    if not configured():
        raise DriveError(503, "Google Drive is not configured (missing GOOGLE_CLIENT_ID/SECRET)")


def auth_url() -> str:
    _require_configured()
    verifier = secrets.token_urlsafe(64)
    state = secrets.token_urlsafe(24)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=")
    with _lock:
        _pending[state] = verifier
    return AUTH_URL + "?" + urlencode(
        {
            "client_id": settings.google_client_id,
            "redirect_uri": settings.drive_redirect_uri,
            "response_type": "code",
            "scope": SCOPE,
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
            "code_challenge": challenge.decode(),
            "code_challenge_method": "S256",
        }
    )


def _token_request(data: dict) -> dict:
    r = httpx.post(
        TOKEN_URL,
        data={
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            **data,
        },
        timeout=20,
    )
    if r.status_code != 200:
        raise DriveError(400, f"Google rejected the sign-in: {r.text[:200]}")
    return r.json()


def finish_login(code: str, state: str) -> None:
    with _lock:
        verifier = _pending.pop(state, None)
    if verifier is None:
        raise DriveError(400, "Unknown or expired sign-in attempt")
    body = _token_request(
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": settings.drive_redirect_uri,
            "code_verifier": verifier,
        }
    )
    if not body.get("refresh_token"):
        raise DriveError(400, "Google did not return a refresh token; try signing in again")
    _save(
        {
            "access_token": body["access_token"],
            "refresh_token": body["refresh_token"],
            "expires_at": time.time() + body.get("expires_in", 3600),
        }
    )


def logout() -> None:
    _token_path().unlink(missing_ok=True)


def _access_token() -> str:
    _require_configured()
    tok = _load()
    if not tok:
        raise DriveError(401, "Not signed in to Google Drive")
    if tok["expires_at"] - time.time() > 60:
        return tok["access_token"]
    try:
        body = _token_request({"grant_type": "refresh_token", "refresh_token": tok["refresh_token"]})
    except DriveError:
        logout()
        raise DriveError(401, "Google sign-in expired; please sign in again")
    tok["access_token"] = body["access_token"]
    tok["expires_at"] = time.time() + body.get("expires_in", 3600)
    _save(tok)
    return tok["access_token"]


def api_get(path: str, params: dict, resource_keys: str | None = None) -> dict:
    headers = {"Authorization": f"Bearer {_access_token()}"}
    if resource_keys:
        headers["X-Goog-Drive-Resource-Keys"] = resource_keys
    r = httpx.get(f"{API}{path}", params=params, headers=headers, timeout=30)
    if r.status_code == 401:
        raise DriveError(401, "Google sign-in expired; please sign in again")
    if r.status_code == 404:
        raise DriveError(404, "Not found, or you have no permission to view it")
    if r.status_code == 403:
        raise DriveError(403, "Google denied access to this item")
    if r.status_code >= 400:
        raise DriveError(502, f"Google Drive error {r.status_code}")
    return r.json()


def download(
    file_id: str,
    dest: Path,
    resource_key: str | None = None,
    on_bytes: Callable[[int], None] | None = None,
    attempts: int = 5,
    cancel_event: threading.Event | None = None,
) -> None:
    """Stream a Drive file to dest, resuming from the bytes already on disk and retrying."""
    last: Exception | None = None
    for attempt in range(attempts):
        _raise_if_cancelled(cancel_event)
        if attempt:
            if cancel_event and cancel_event.wait(min(2**attempt, 20)):
                raise DownloadCancelled("Google Drive download cancelled")
            if not cancel_event:
                time.sleep(min(2**attempt, 20))
        offset = dest.stat().st_size if dest.exists() else 0
        headers = {"Authorization": f"Bearer {_access_token()}"}
        if offset:
            headers["Range"] = f"bytes={offset}-"
        if resource_key:
            headers["X-Goog-Drive-Resource-Keys"] = f"{file_id}/{resource_key}"
        try:
            with httpx.stream(
                "GET",
                f"{API}/files/{file_id}",
                params={"alt": "media", "supportsAllDrives": "true"},
                headers=headers,
                timeout=httpx.Timeout(30, read=60),
            ) as r:
                if r.status_code == 416:  # already complete
                    return
                if r.status_code in (401, 403, 404):
                    raise DriveError(r.status_code, "Google denied access to this file")
                if r.status_code in (429, 500, 502, 503, 504):
                    last = DriveError(502, f"Google Drive error {r.status_code}")
                    continue
                if r.status_code >= 400:
                    raise DriveError(502, f"Google Drive error {r.status_code}")
                if offset and r.status_code == 200:  # server ignored Range
                    offset = 0
                with dest.open("ab" if offset else "wb") as f:
                    for chunk in r.iter_bytes(1024 * 1024):
                        _raise_if_cancelled(cancel_event)
                        f.write(chunk)
                        if on_bytes:
                            on_bytes(len(chunk))
                return
        except httpx.TransportError as e:
            last = DriveError(502, f"Network error: {type(e).__name__}")
    raise last or DriveError(502, "Download failed")


def _item(f: dict) -> dict:
    mime = f.get("mimeType", "")
    if mime == FOLDER:
        kind = "folder"
    elif mime.startswith("image/"):
        kind = "image"
    elif mime.startswith("video/"):
        kind = "video"
    else:
        kind = "other"
    return {
        "id": f["id"],
        "name": f["name"],
        "kind": kind,
        "mime": mime,
        "size": int(f["size"]) if f.get("size") else None,
        "resource_key": f.get("resourceKey"),
    }


def status() -> dict:
    if not configured():
        return {"configured": False, "connected": False, "email": None}
    if not _load():
        return {"configured": True, "connected": False, "email": None}
    try:
        user = api_get("/about", {"fields": "user(emailAddress)"})["user"]
        return {"configured": True, "connected": True, "email": user.get("emailAddress")}
    except DriveError as e:
        if e.status == 401:
            return {"configured": True, "connected": False, "email": None}
        raise


def list_items(
    parent: str, page_token: str | None = None, resource_key: str | None = None
) -> dict:
    """parent: 'root', 'shared' (shared with me) or a folder id."""
    q = (
        "sharedWithMe=true"
        if parent == "shared"
        else f"'{parent.replace(chr(39), '')}' in parents"
    )
    params = {
        "q": f"{q} and trashed=false and {_KIND_FILTER}",
        "fields": f"nextPageToken,files({_FIELDS})",
        "orderBy": "folder,name",
        "pageSize": 100,
        "supportsAllDrives": "true",
        "includeItemsFromAllDrives": "true",
    }
    if page_token:
        params["pageToken"] = page_token
    keys = f"{parent}/{resource_key}" if resource_key and parent not in ("root", "shared") else None
    body = api_get("/files", params, keys)
    return {
        "items": [_item(f) for f in body.get("files", [])],
        "next_page_token": body.get("nextPageToken"),
    }


_LINK_PATTERNS = [r"/folders/([\w-]+)", r"/file/d/([\w-]+)", r"/d/([\w-]+)"]


def parse_link(url: str) -> tuple[str, str | None]:
    """Extract (file or folder id, resource key) from a Drive share link."""
    parsed = urlparse(url.strip())
    if parsed.hostname not in ("drive.google.com", "docs.google.com"):
        raise DriveError(422, "Not a Google Drive link")
    query = parse_qs(parsed.query)
    key = (query.get("resourcekey") or [None])[0]
    for pattern in _LINK_PATTERNS:
        m = re.search(pattern, parsed.path)
        if m:
            return m.group(1), key
    if query.get("id"):
        return query["id"][0], key
    raise DriveError(422, "Could not find a file or folder in this link")


def resolve_link(url: str) -> dict:
    file_id, key = parse_link(url)
    f = api_get(
        f"/files/{file_id}",
        {"fields": _FIELDS, "supportsAllDrives": "true"},
        f"{file_id}/{key}" if key else None,
    )
    item = _item(f)
    item["resource_key"] = item["resource_key"] or key
    if item["kind"] == "other":
        raise DriveError(422, "The link is not a folder, image or video")
    return item
