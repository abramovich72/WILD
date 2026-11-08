# Wild Clips — Project and Architecture Guide

This document is a quick-start context guide for a new developer or AI assistant. It describes the current implementation, not just the original plan. Read it together with `IMPLEMENTATION_PLAN.md` and `GAPS.md` when picking up work.

## 1. Product overview

Wild Clips is a local-first web application for organizing trail-camera photos and videos, detecting animals, assembling selected media into short clips, and exporting MP4 files.

Current product capabilities:

- React + TypeScript frontend with a Hebrew, right-to-left (RTL) interface.
- Python + FastAPI backend.
- Import images/videos from the local computer or Google Drive.
- Store media and generated assets on the local filesystem; keep metadata in SQLite.
- Run animal detection with SpeciesNet, configured for Israel (`country=ISR`), primarily on CPU.
- Browse and correct detections; display Hebrew species names using `backend/app/data/species_he.json`.
- Compose a timeline by dragging media/detections, reorder segments, and render MP4 clips with FFmpeg.
- Add optional opening and closing title cards, each with its own text and duration; optionally overlay animal captions.
- Preview videos, transcoding formats not natively playable in browsers to a cached MP4.

The application is **not yet a public cloud service**. There is no user authentication or multi-tenant isolation. SQLite, process-local background queues, and local disk are used today. Cloud deployment, PostgreSQL, object storage, and production-grade job infrastructure are future work.

## 2. Technology and runtime

| Area | Current implementation |
|---|---|
| Frontend | React 19, TypeScript, Vite |
| Backend | Python, FastAPI, Uvicorn |
| ORM/database | SQLModel + SQLite |
| Media processing | FFmpeg and ffprobe |
| Animal detection | SpeciesNet, with configurable CPU-oriented inference settings |
| Google integration | Drive API v3 OAuth authorization-code flow with PKCE and `drive.readonly`; controlled by `DRIVE_ENABLED` |
| Background work | In-process Python worker threads and queues |
| Local development | `run.cmd` launches the backend and Vite frontend |

Default development ports in `run.ps1` are backend `8010` and frontend `5180`. The launcher sets `API_URL` for Vite's `/api` proxy. Running Vite directly uses the fallback backend URL in `frontend/vite.config.ts` (port `8000`), so prefer `run.cmd` unless intentionally configuring ports.

## 3. Repository map

```text
wild/
  run.cmd, run.ps1                 Local development launcher
  IMPLEMENTATION_PLAN.md           Stage plan and completion checklist
  GAPS.md                          Known limitations and unverified behavior
  PROJECT_ARCHITECTURE.md          This guide
  backend/
    app/
      main.py                      FastAPI application and lifespan setup
      config.py                    Environment-backed settings
      db.py                        SQLite engine, initialization, small migrations
      api/
        routes.py                  Projects, media, upload, preview, delete
        detect.py                  Detection API, results, and SSE progress
        clips.py                   Timeline planning and clip APIs
        drive.py                   Google Drive OAuth, browsing, and import APIs
      models/media.py              Project, MediaItem, Detection, Clip tables
      services/
        storage.py                 Local media storage and ingest pipeline
        ffmpeg.py                  Media probing, thumbnails, and browser previews
        detect.py                  SpeciesNet loading and inference helpers
        jobs.py                    In-process detection worker
        species_names.py           English-to-Hebrew display-name lookup
        clip.py                    Timeline planning and FFmpeg rendering
        renders.py                 In-process clip-render worker
        gdrive.py                  OAuth tokens, Drive API, and downloads
        drive_import.py            In-process Drive import queue and deduplication
      data/species_he.json         Species display-name translations
    tests/                         Backend pytest tests
  frontend/
    src/
      App.tsx                      Main app state and feature wiring
      api.ts                       Frontend API types and HTTP functions
      App.css, index.css           Layout and RTL styles
      components/
        MediaGrid.tsx              Media library, selection, and deletion
        UploadZone.tsx             Local resumable uploads
        Preview.tsx                Image/video preview and detection overlays
        DetectionsPanel.tsx        Detection list and corrections
        TimelinePanel.tsx          Timeline editing and seconds ruler
        SettingsPanel.tsx          Clip, captions, title-card, and transition settings
        ClipsPanel.tsx              Rendered clip list, playback, download, delete
        DriveDialog.tsx            Google Drive browsing and import
```

## 4. High-level architecture

```text
Browser (React/Vite)
  ├─ Local upload ────────────────┐
  ├─ Google Drive OAuth/browse ───┤ HTTP /api
  ├─ Media preview and timeline ──┤
  └─ Polls clips; listens to SSE ─┘
                                  ↓
FastAPI (backend/app/main.py)
  ├─ API routers: general media, detection, clips, Drive
  ├─ SQLModel ── SQLite (storage/wild.db)
  ├─ In-process detection worker ── SpeciesNet + FFmpeg
  ├─ In-process render worker ───── FFmpeg
  ├─ In-process Drive worker ────── Google Drive API
  └─ Local storage ── originals, thumbnails, previews, clips, temp uploads
```

The browser does not call Google Drive directly. The backend owns OAuth credentials/tokens and proxies Drive operations.

## 5. Main data model

- **Project**: project name and creation time.
- **MediaItem**: project relation, original filename, image/video kind, generated stored filename, thumbnail, size and media metadata, detection status/error, optional Google Drive file ID.
- **Detection**: detected species, confidence, optional video time span, optional normalized bounding box, and whether a user corrected the result.
- **Clip**: project relation, name, render status/error, output filename/metadata, and a JSON `spec` with normalized timeline items and render settings.

The current UI loads the first project returned by the API, creating a default project if none exists. A full project-management UI is not implemented.

### Detection states

`pending → queued → running → done | failed`

`done` means the analysis finished; it does not mean that an animal was found. A completed media item with no detection is displayed as “לא זוהה” (“Not detected”).

## 6. Important workflows

### Local upload

1. The frontend initializes a resumable upload and sends chunks.
2. The backend checks the declared size/type and writes temporary files under `storage/uploads/`.
3. Completion moves the original into the project media directory, probes it with ffprobe, creates a thumbnail, then inserts the `MediaItem` row.

### Google Drive import

1. The backend performs OAuth with PKCE and the `drive.readonly` scope; its token is stored under the configured storage directory.
2. The frontend browses “My Drive” or “Shared with me”, opens folders, or resolves a pasted Drive link/resource key.
3. Selected files/folders are processed by an in-process background queue. Folder recursion is controlled by the UI option.
4. Files are downloaded with streaming/range-resume retries, ingested through the same storage pipeline, and associated with their Drive ID for project-level duplicate skipping.
5. The frontend polls import status and refreshes the media list.

Google credentials belong in `backend/.env`; never include secret values in source, documentation, logs, or chat. `backend/.env` and token files must remain untracked. Drive tokens and in-memory jobs are local development state, not durable production infrastructure.

### Animal detection

1. The frontend submits a project and optional media IDs to `POST /api/projects/{id}/detect`; `force=true` requests re-detection.
2. `services/jobs.py` queues media IDs on an in-process worker thread.
3. Images are analyzed directly; videos are sampled with FFmpeg, with near-identical frames skipped subject to a maximum skip interval.
4. SpeciesNet predictions are filtered and merged into detection events. Results are saved in SQLite.
5. `GET /api/projects/{id}/detect/events` streams progress/status snapshots over Server-Sent Events (SSE).
6. API responses resolve translated names through `services/species_names.py`; edit `data/species_he.json` to add translations.

When re-detecting, uncorrected prior detections are replaced. Corrected detections are retained by default (`keep_corrections=true`) and overlapping new results are suppressed.

### Clip rendering

1. The user assembles and edits a timeline in the frontend. Timeline state is stored in browser `localStorage`, not the server.
2. `POST /api/projects/{id}/clips` validates timeline media/segments and saves a JSON render spec.
3. `services/renders.py` runs the clip on a background worker; `services/clip.py` produces normalized 1280×720, 30 fps H.264 MP4 segments and concatenates them.
4. Optional animal-name captions are drawn on timeline segments. Optional opening and closing title cards use a black background with centered text and configurable durations (1–60 seconds).
5. The frontend polls the clip list for queued/running/done/failed status. Completed clips can be previewed, downloaded, and deleted.

The current renderer has no soundtrack. Music generation/mixing is planned for a later stage.

### Media preview and deletion

- Browser-compatible videos are served directly. Other video containers are transcoded once to a cached MP4 for preview; the original is retained for detection/rendering.
- Deleting a media item removes its original, thumbnail, cached preview, detection rows, and media row. The UI also removes it from the in-memory detection list and timeline.
- Multi-select in the media library supports batch deletion after confirmation. The same selection can be used to request re-detection.

## 7. API map

All endpoints are under `/api`.

| Router/file | Main routes |
|---|---|
| `api/routes.py` | `/health` is in `main.py`; projects, project media, upload initialization/chunks/completion, media file/preview/thumb, media delete |
| `api/detect.py` | `POST /projects/{id}/detect`, `GET /projects/{id}/detections`, `GET /projects/{id}/detect/events`, correction/delete detection |
| `api/clips.py` | `POST /projects/{id}/timeline/auto`, create/list clips, clip file, clip delete |
| `api/drive.py` | Drive status/auth/callback/logout, files, resolve link, start import, import status, imported IDs |

The React API client and TypeScript response contracts live in `frontend/src/api.ts`.

## 8. Configuration and local storage

Settings are defined in `backend/app/config.py` and can be overridden with environment variables or `backend/.env`. Common settings include:

- `STORAGE_DIR`
- `MAX_UPLOAD_BYTES` (50 MB by default and for the private cloud trial; `50000000` bytes)
- `MAX_STORAGE_BYTES` (0 means unlimited locally; use `150000000000` for a shared 150 GB cloud quota)
- `UPLOAD_TTL_SECONDS` (0 disables expiry locally; use `86400` for the 24-hour cloud trial cleanup)
- `DEVICE`
- `FFMPEG_PATH`, `FFPROBE_PATH`
- Detection settings such as `DETECT_COUNTRY`, `DETECT_FPS`, and confidence/frame-skip thresholds
- `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `DRIVE_REDIRECT_URI`, `FRONTEND_URL`
- `DRIVE_ENABLED` (defaults to `true` for local development; set to `false` for the private cloud trial)
- `PRELOAD_MODEL`
- `CAPTION_FONT`, `MAX_CLIP_SECONDS`

The shared storage quota counts files under `storage/projects/` and active upload reservations. It does not count the SQLite database or Google OAuth token. Expired partial uploads are removed only when `UPLOAD_TTL_SECONDS` is positive.

Do not paste `.env` values into tickets or docs. Configuration is read at backend startup; restart the backend after changes.

Typical local storage layout:

```text
storage/
  wild.db
  google_token.json
  uploads/                         Incomplete uploads and temporary Drive downloads
  projects/<project-id>/
    media/                         Original media
    thumbs/                        Generated image thumbnails
    previews/                      Cached browser-compatible MP4 previews
    clips/                         Rendered clips and temporary render directories
```

## 9. Development and validation

From the repository root on Windows:

```powershell
.\run.cmd
```

The default app URL is `http://localhost:5180`; backend health is `http://localhost:8010/api/health`.

Frontend:

```powershell
Set-Location frontend
npm.cmd run lint
npm.cmd run build
```

Backend:

```powershell
Set-Location backend
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\ruff.exe check .
```

The backend tests use temporary SQLite databases and mock external Google services. FFmpeg-based tests exercise actual local rendering. There is currently no frontend unit-test runner configured.

## 10. Known constraints and guidance for future work

- The application currently targets local/single-user use; it is not safe to expose publicly as-is.
- Background queues, detection progress, and Drive import jobs are held in process memory. A server restart interrupts queued/running work; detection jobs are reset during database initialization.
- SQLite initialization uses `create_all` plus a small hand-written migration helper in `db.py`; there is no general migration framework.
- Timeline edits are browser-local and are not persisted to the backend.
- Drive OAuth testing mode may require users to sign in again after token expiry. Public use of `drive.readonly` requires Google verification.
- Google-native documents and Shared Drives as a browsing root are not supported.
- MusicGen, soundtrack mixing, a full outputs/project-management UI, persistent job infrastructure, and cloud deployment remain planned/incomplete. See `GAPS.md` for current details.
- Preserve Hebrew UI strings, RTL layout, existing API/type patterns, and the original source files when adding features.
- Keep changes surgical; add tests for backend behavior and run the narrowest applicable checks, then expand validation as needed.
