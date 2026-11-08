export type Project = { id: number; name: string }

export type MediaItem = {
  id: number
  project_id: number
  filename: string
  kind: 'video' | 'image'
  thumb_name: string | null
  size_bytes: number
  duration: number | null
  width: number | null
  height: number | null
  detect_status: DetectStatus
  detect_error: string | null
}

export type DetectStatus = 'pending' | 'queued' | 'running' | 'done' | 'failed'

export type Detection = {
  id: number
  media_id: number
  species: string
  display: string
  confidence: number
  source: 'speciesnet' | 'manual'
  start_time: number | null
  end_time: number | null
  box_x: number | null
  box_y: number | null
  box_w: number | null
  box_h: number | null
  corrected: boolean
}

export type SpeciesOption = { species: string; display: string }

export type DetectProgress = {
  id: number
  status: DetectStatus
  error: string | null
  progress: number | null
}

export type TimelineItem = {
  uid: string
  media_id: number
  start: number
  end: number
  label: string | null
}

export type Transition = 'none' | 'fade'

export type DriveStatus = {
  enabled: boolean
  configured: boolean
  connected: boolean
  email: string | null
}

export type DriveItem = {
  id: string
  name: string
  kind: 'folder' | 'image' | 'video' | 'other'
  mime: string
  size: number | null
  resource_key: string | null
}

export type DriveListing = { items: DriveItem[]; next_page_token: string | null }

async function driveJson<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = ''
    try {
      detail = (await res.json()).detail
    } catch {
      /* not JSON */
    }
    throw new Error(detail || `${res.status}`)
  }
  return res.json() as Promise<T>
}

export const drive = {
  status: () => fetch('/api/drive/status').then(driveJson<DriveStatus>),
  authUrl: () => fetch('/api/drive/auth-url').then(driveJson<{ url: string }>),
  logout: () => fetch('/api/drive/logout', { method: 'POST' }),
  files: (parent: string, pageToken?: string | null, resourceKey?: string | null) => {
    const q = new URLSearchParams({ parent })
    if (pageToken) q.set('page_token', pageToken)
    if (resourceKey) q.set('resource_key', resourceKey)
    return fetch(`/api/drive/files?${q}`).then(driveJson<DriveListing>)
  },
  resolve: (url: string) =>
    fetch('/api/drive/resolve', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url }),
    }).then(driveJson<DriveItem>),
  imported: (projectId: number) =>
    fetch(`/api/drive/imported/${projectId}`).then(driveJson<string[]>),
  startImport: (projectId: number, items: DriveItem[], recursive: boolean) =>
    fetch('/api/drive/import', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ project_id: projectId, items, recursive }),
    }).then(driveJson<DriveImportJob>),
  importJob: (id: string) => fetch(`/api/drive/imports/${id}`).then(driveJson<DriveImportJob>),
  activeImport: () => fetch('/api/drive/imports/active').then(driveJson<DriveImportJob | null>),
  cancelImport: (id: string) =>
    fetch(`/api/drive/imports/${id}/cancel`, { method: 'POST' }).then(driveJson<DriveImportJob>),
}

export type DriveImportJob = {
  id: string
  project_id: number
  status: 'queued' | 'running' | 'done' | 'failed' | 'cancelled'
  phase: string
  total: number
  done: number
  skipped: number
  failed: number
  current: string | null
  bytes_done: number
  errors: { name: string; error: string }[]
}

export type Clip = {
  id: number
  name: string
  status: 'queued' | 'running' | 'done' | 'failed'
  error: string | null
  progress: number | null
  duration: number | null
  size_bytes: number
  created_at: string
  spec: {
    items: Omit<TimelineItem, 'uid'>[]
    captions: boolean
    opening_title?: string
    opening_title_seconds?: number
    closing_title?: string
    closing_title_seconds?: number
    transition: Transition
  }
}

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`)
  return res.json() as Promise<T>
}

const send = (method: string, body: unknown) => ({
  method,
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
})

export const api = {
  projects: () => fetch('/api/projects').then(json<Project[]>),
  createProject: (name: string) =>
    fetch('/api/projects', send('POST', { name })).then(json<Project>),
  renameProject: (id: number, name: string) =>
    fetch(`/api/projects/${id}`, send('PATCH', { name })).then(json<Project>),
  media: (projectId: number) =>
    fetch(`/api/projects/${projectId}/media`).then(json<MediaItem[]>),
  deleteMedia: async (id: number) => {
    const res = await fetch(`/api/media/${id}`, { method: 'DELETE' })
    if (!res.ok) throw new Error(`${res.status}`)
  },
  detect: (projectId: number, body: { media_ids?: number[]; force?: boolean; keep_corrections?: boolean }) =>
    fetch(`/api/projects/${projectId}/detect`, send('POST', body)).then(
      json<{ queued: number; skipped: number }>,
    ),
  detections: (projectId: number) =>
    fetch(`/api/projects/${projectId}/detections`).then(json<Detection[]>),
  species: () => fetch('/api/species').then(json<SpeciesOption[]>),
  createDetection: (
    mediaId: number,
    body: { species: string; start_time: number | null; end_time: number | null },
  ) => fetch(`/api/media/${mediaId}/detections`, send('POST', body)).then(json<Detection>),
  updateDetection: (
    id: number,
    body: { species?: string; start_time?: number | null; end_time?: number | null },
  ) => fetch(`/api/detections/${id}`, send('PATCH', body)).then(json<Detection>),
  correctDetection: (id: number, species: string) =>
    fetch(`/api/detections/${id}`, send('PATCH', { species })).then(json<Detection>),
  deleteDetection: async (id: number) => {
    const res = await fetch(`/api/detections/${id}`, { method: 'DELETE' })
    if (!res.ok) throw new Error(`${res.status}`)
  },
  detectEventsUrl: (projectId: number) => `/api/projects/${projectId}/detect/events`,
  autoTimeline: (
    projectId: number,
    body: { media_ids?: number[]; length: number; animals_only: boolean },
  ) =>
    fetch(`/api/projects/${projectId}/timeline/auto`, send('POST', body)).then(
      json<{ items: Omit<TimelineItem, 'uid'>[]; total: number; skipped: number }>,
    ),
  createClip: (
    projectId: number,
    body: {
      items: Omit<TimelineItem, 'uid'>[]
      captions: boolean
      opening_title: string
      opening_title_seconds: number
      closing_title: string
      closing_title_seconds: number
      transition: Transition
    },
  ) => fetch(`/api/projects/${projectId}/clips`, send('POST', body)).then(json<Clip>),
  clips: (projectId: number) => fetch(`/api/projects/${projectId}/clips`).then(json<Clip[]>),
  deleteClip: async (id: number) => {
    const res = await fetch(`/api/clips/${id}`, { method: 'DELETE' })
    if (!res.ok) throw new Error(`${res.status}`)
  },
  clipUrl: (id: number, download = false) => `/api/clips/${id}/file${download ? '?download=true' : ''}`,
  fileUrl: (id: number) => `/api/media/${id}/file`,
  previewUrl: (id: number) => `/api/media/${id}/preview`,
  thumbUrl: (id: number) => `/api/media/${id}/thumb`,
}

export const MAX_UPLOAD_BYTES = 50_000_000

const CHUNK = 8 * 1024 * 1024

// Resumable chunked upload: asks the server for its offset after a failed chunk and continues.
export async function uploadFile(
  projectId: number,
  file: File,
  onProgress: (fraction: number) => void,
): Promise<MediaItem> {
  const init = await fetch(
    `/api/projects/${projectId}/uploads`,
    send('POST', { filename: file.name, size: file.size }),
  ).then(json<{ upload_id: string }>)
  const url = `/api/uploads/${init.upload_id}`
  let offset = 0
  let failures = 0
  while (offset < file.size) {
    const end = Math.min(offset + CHUNK, file.size)
    try {
      const res = await fetch(`${url}?offset=${offset}`, {
        method: 'PUT',
        body: file.slice(offset, end),
      })
      if (!res.ok) throw new Error(String(res.status))
      offset = (await res.json()).offset
      failures = 0
      onProgress(offset / file.size)
    } catch (e) {
      if (++failures > 5) throw e
      await new Promise((r) => setTimeout(r, 1000 * failures))
      offset = (await fetch(url).then(json<{ offset: number }>)).offset
    }
  }
  return fetch(`${url}/complete`, { method: 'POST' }).then(json<MediaItem>)
}
