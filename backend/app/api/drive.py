from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlmodel import Session

from ..config import settings
from ..db import get_session
from ..models.media import Project
from ..services import drive_import, gdrive


def _require_enabled() -> None:
    if not settings.drive_enabled:
        raise HTTPException(503, "Google Drive is disabled on this server")


router = APIRouter(prefix="/api/drive")
protected_router = APIRouter(
    prefix="/api/drive",
    dependencies=[Depends(_require_enabled)],
)


def _fail(e: gdrive.DriveError) -> HTTPException:
    return HTTPException(e.status, e.message)


class LinkIn(BaseModel):
    url: str


@router.get("/status")
def status():
    if not settings.drive_enabled:
        return {"enabled": False, "configured": False, "connected": False, "email": None}
    try:
        return {"enabled": True, **gdrive.status()}
    except gdrive.DriveError as e:
        raise _fail(e)


@protected_router.get("/auth-url")
def auth_url():
    try:
        return {"url": gdrive.auth_url()}
    except gdrive.DriveError as e:
        raise _fail(e)


@protected_router.get("/callback")
def callback(code: str | None = None, state: str | None = None, error: str | None = None):
    base = settings.frontend_url
    if error or not code or not state:
        return RedirectResponse(f"{base}?drive=denied")
    try:
        gdrive.finish_login(code, state)
    except gdrive.DriveError:
        return RedirectResponse(f"{base}?drive=failed")
    return RedirectResponse(f"{base}?drive=connected")


@protected_router.post("/logout", status_code=204)
def logout():
    gdrive.logout()


@protected_router.get("/files")
def files(parent: str = "root", page_token: str | None = None, resource_key: str | None = None):
    try:
        return gdrive.list_items(parent, page_token, resource_key)
    except gdrive.DriveError as e:
        raise _fail(e)


@protected_router.post("/resolve")
def resolve(body: LinkIn):
    try:
        return gdrive.resolve_link(body.url)
    except gdrive.DriveError as e:
        raise _fail(e)


class ImportItem(BaseModel):
    id: str
    name: str
    kind: str
    mime: str = ""
    size: int | None = None
    resource_key: str | None = None


class ImportIn(BaseModel):
    project_id: int
    items: list[ImportItem]
    recursive: bool = False


@protected_router.post("/import", status_code=202)
def start_import(body: ImportIn, session: Session = Depends(get_session)):
    if not session.get(Project, body.project_id):
        raise HTTPException(404, "Project not found")
    if not body.items:
        raise HTTPException(422, "Nothing selected")
    if any(i.kind not in ("folder", "image", "video") for i in body.items):
        raise HTTPException(422, "Unsupported item kind")
    try:
        gdrive.status()
    except gdrive.DriveError as e:
        raise _fail(e)
    try:
        return drive_import.create_job(
            body.project_id, [i.model_dump() for i in body.items], body.recursive
        )
    except drive_import.ImportAlreadyRunning as e:
        raise HTTPException(409, "A Google Drive import is already running") from e


@protected_router.get("/imports/active")
def active_import():
    return drive_import.active_job()


@protected_router.post("/imports/{job_id}/cancel")
def cancel_import(job_id: str):
    try:
        return drive_import.cancel_job(job_id)
    except KeyError as e:
        raise HTTPException(404, "Import not found") from e
    except drive_import.ImportNotActive as e:
        raise HTTPException(409, "Import is no longer active") from e


@protected_router.get("/imports/{job_id}")
def import_status(job_id: str):
    job = drive_import.JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "Import not found")
    return drive_import.public(job)


@protected_router.get("/imported/{project_id}")
def imported(project_id: int):
    return drive_import.imported_ids(project_id)
