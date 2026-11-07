import { useEffect, useMemo, useRef, useState } from 'react'
import {
  api,
  type Clip,
  type DetectProgress,
  type Detection,
  type MediaItem,
  type Project,
  type TimelineItem,
  type Transition,
} from './api'
import { formatDuration } from './format'
import { ClipsPanel } from './components/ClipsPanel'
import { DetectionsPanel } from './components/DetectionsPanel'
import { DriveDialog } from './components/DriveDialog'
import { MediaGrid } from './components/MediaGrid'
import { SoundtrackPanel } from './components/Placeholders'
import { Preview } from './components/Preview'
import { SettingsPanel } from './components/SettingsPanel'
import { TimelinePanel } from './components/TimelinePanel'
import { UploadZone } from './components/UploadZone'
import './App.css'

const IMAGE_SECONDS = 3
const uid = () => Math.random().toString(36).slice(2)
const timelineKey = (projectId: number) => `timeline:${projectId}`

function App() {
  const [project, setProject] = useState<Project | null>(null)
  const [items, setItems] = useState<MediaItem[]>([])
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [checked, setChecked] = useState<Set<number>>(new Set())
  const [length, setLength] = useState(30)
  const [editing, setEditing] = useState(false)
  const [activeTab, setActiveTab] = useState<'edit' | 'outputs'>('edit')
  const [error, setError] = useState('')
  const [detections, setDetections] = useState<Detection[]>([])
  const [progress, setProgress] = useState<Record<number, number | null>>({})
  const [detectionBatch, setDetectionBatch] = useState<number[]>([])
  const [seek, setSeek] = useState<{ time: number; n: number } | null>(null)
  const [timeline, setTimeline] = useState<TimelineItem[]>([])
  const [captions, setCaptions] = useState(true)
  const [openingTitle, setOpeningTitle] = useState('')
  const [openingTitleSeconds, setOpeningTitleSeconds] = useState(3)
  const [closingTitle, setClosingTitle] = useState('')
  const [closingTitleSeconds, setClosingTitleSeconds] = useState(3)
  const [transition, setTransition] = useState<Transition>('fade')
  const [clips, setClips] = useState<Clip[]>([])
  const [note, setNote] = useState('')
  const [rendering, setRendering] = useState(false)
  const [showDrive, setShowDrive] = useState(() => new URLSearchParams(location.search).has('drive'))
  const source = useRef<EventSource | null>(null)
  const timelineLoaded = useRef(false)

  async function refresh(projectId: number) {
    const [media, dets] = await Promise.all([api.media(projectId), api.detections(projectId)])
    setItems(media)
    setDetections(dets)
  }

  function listen(projectId: number) {
    source.current?.close()
    const es = new EventSource(api.detectEventsUrl(projectId))
    source.current = es
    es.onmessage = (e) => {
      const snap: DetectProgress[] = JSON.parse(e.data)
      setProgress(Object.fromEntries(snap.map((s) => [s.id, s.progress])))
      setItems((list) =>
        list.map((m) => {
          const s = snap.find((x) => x.id === m.id)
          return s ? { ...m, detect_status: s.status, detect_error: s.error } : m
        }),
      )
    }
    es.addEventListener('idle', () => {
      es.close()
      setProgress({})
      void refresh(projectId)
    })
    es.onerror = () => es.close()
  }

  async function startDetection(force: boolean, ids?: number[]) {
    if (!project) return
    try {
      const result = await api.detect(project.id, { media_ids: ids, force })
      setDetectionBatch(result.queued_ids)
      listen(project.id)
    } catch {
      setError('לא ניתן להתחבר לשרת')
    }
  }

  useEffect(() => {
    ;(async () => {
      try {
        const list = await api.projects()
        const p = list[0] ?? (await api.createProject('הפרויקט שלי'))
        setProject(p)
        const [media] = await Promise.all([
          api.media(p.id).then((m) => {
            setItems(m)
            return m
          }),
          api.detections(p.id).then(setDetections),
          api.clips(p.id).then(setClips),
        ])
        try {
          const saved: TimelineItem[] = JSON.parse(localStorage.getItem(timelineKey(p.id)) ?? '[]')
          const ids = new Set(media.map((m) => m.id))
          setTimeline(saved.filter((t) => ids.has(t.media_id)))
        } catch {
          setTimeline([])
        }
        timelineLoaded.current = true
        if (media.some((m) => m.detect_status === 'queued' || m.detect_status === 'running'))
          listen(p.id)
      } catch {
        setError('לא ניתן להתחבר לשרת')
      }
    })()
    return () => source.current?.close()
  }, [])

  useEffect(() => {
    if (project && timelineLoaded.current)
      localStorage.setItem(timelineKey(project.id), JSON.stringify(timeline))
  }, [timeline, project])

  const rendersActive = clips.some((c) => c.status === 'queued' || c.status === 'running')
  useEffect(() => {
    if (!project || !rendersActive) return
    const id = setInterval(() => void api.clips(project.id).then(setClips).catch(() => {}), 1000)
    return () => clearInterval(id)
  }, [project, rendersActive])

  const topSpecies = useMemo(() => {
    const best = new Map<number, Detection>()
    for (const d of detections) {
      const cur = best.get(d.media_id)
      if (!cur || d.confidence > cur.confidence) best.set(d.media_id, d)
    }
    return new Map([...best].map(([id, d]) => [id, d.display]))
  }, [detections])

  if (error) return <p className="error page">{error}</p>
  if (!project) return <p className="muted page">טוען…</p>

  const selected = items.find((m) => m.id === selectedId) ?? null
  const active = items.filter((m) => m.detect_status === 'queued' || m.detect_status === 'running')
  const running = active.length ? active : null
  const pendingCount = items.filter(
    (m) => m.detect_status === 'pending' || m.detect_status === 'failed',
  ).length
  const detectionTargets = checked.size > 0 ? [...checked] : selected ? [selected.id] : []
  const detectionBatchItems = items.filter((m) => detectionBatch.includes(m.id))
  const detectionBatchDone = detectionBatchItems.filter((m) => m.detect_status === 'done').length
  const detectionBatchFailed = detectionBatchItems.filter(
    (m) => m.detect_status === 'failed',
  ).length
  const detectionBatchCompleted = detectionBatchDone + detectionBatchFailed

  async function rename(name: string) {
    setEditing(false)
    if (!project || !name.trim() || name === project.name) return
    setProject(await api.renameProject(project.id, name))
  }

  function toggleChecked(id: number) {
    setChecked((s) => {
      const next = new Set(s)
      if (!next.delete(id)) next.add(id)
      return next
    })
  }

  function addSelected() {
    if (!selected) return
    const end = selected.kind === 'image' ? IMAGE_SECONDS : (selected.duration ?? 0)
    if (end <= 0) return
    const label = topSpecies.get(selected.id) ?? null
    setTimeline((t) => [
      ...t,
      { uid: uid(), media_id: selected.id, start: 0, end: Math.round(end * 100) / 100, label },
    ])
  }

  async function renderClip() {
    if (!project || timeline.length === 0) return
    setRendering(true)
    setNote('')
    try {
      await api.createClip(project.id, {
        items: timeline.map(({ media_id, start, end, label }) => ({ media_id, start, end, label })),
        captions,
        opening_title: openingTitle,
        opening_title_seconds: openingTitleSeconds,
        closing_title: closingTitle,
        closing_title_seconds: closingTitleSeconds,
        transition,
      })
      setClips(await api.clips(project.id))
      setActiveTab('outputs')
    } catch (e) {
      setNote(`יצירת הקליפ נכשלה: ${e instanceof Error ? e.message : ''}`)
    } finally {
      setRendering(false)
    }
  }

  return (
    <div className="app">
      <nav className="tabs" aria-label="ניווט בפרויקט">
        <button
          type="button"
          className={`tab${activeTab === 'edit' ? ' active' : ''}`}
          aria-current={activeTab === 'edit' ? 'page' : undefined}
          onClick={() => setActiveTab('edit')}
        >
          <b>1</b> עריכה
        </button>
        <button
          type="button"
          className={`tab${activeTab === 'outputs' ? ' active' : ''}`}
          aria-current={activeTab === 'outputs' ? 'page' : undefined}
          onClick={() => setActiveTab('outputs')}
        >
          <b>2</b> תוצרים
        </button>
      </nav>

      <div className="page">
        <DriveDialog
          projectId={project.id}
          open={showDrive}
          onOpen={() => setShowDrive(true)}
          onImported={() => void refresh(project.id)}
          onClose={() => {
            setShowDrive(false)
            history.replaceState(null, '', location.pathname)
          }}
        />
        <header className="head">
          <div className="title-block">
            <img className="brand-logo" src="/wild-clips-logo.png" alt="WILD Clips" />
            <div>
              <div className="breadcrumb">הפרויקטים שלי / 01</div>
              {editing ? (
                <input
                  className="title-input"
                  autoFocus
                  defaultValue={project.name}
                  onBlur={(e) => void rename(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && e.currentTarget.blur()}
                />
              ) : (
                <h1>
                  {project.name}
                  <button className="pencil" onClick={() => setEditing(true)} aria-label="שינוי שם">
                    ✎
                  </button>
                </h1>
              )}
              <div className="muted small">
                {items.length} קבצים · {formatDuration(length)}
              </div>
            </div>
          </div>
          <div className="head-actions">
            {activeTab === 'edit' ? (
              <button
                className="primary"
                disabled={timeline.length === 0 || rendering}
                title={timeline.length === 0 ? 'הוסיפו קטעים לציר הזמן' : undefined}
                onClick={() => void renderClip()}
              >
                {rendering ? 'שולח…' : 'הפקת סרטון'}
              </button>
            ) : (
              <button className="primary" onClick={() => setActiveTab('edit')}>
                חזרה לעריכה
              </button>
            )}
          </div>
        </header>

        {activeTab === 'outputs' ? (
          <main className="outputs-page">
            <ClipsPanel
              clips={clips}
              onChanged={() => project && void api.clips(project.id).then(setClips)}
            />
          </main>
        ) : (
        <main className="layout">
          <aside className="panel library-panel">
            <h2>המדיה שלך</h2>
            <button className="filter" onClick={() => setShowDrive(true)}>
              ייבוא מ-Google Drive
            </button>
            <UploadZone
              projectId={project.id}
              onUploaded={(m) => {
                setItems((l) => [...l, m])
                setSelectedId(m.id)
              }}
            />
            <div className="detect-box">
              <div className="row between">
                <strong className="small">זיהוי חיות</strong>
                <span className="muted small">
                  {running
                    ? `${running.filter((m) => m.detect_status === 'running').length ? 'מזהה' : 'בתור'} · ${running.length} נותרו`
                    : `${items.filter((m) => m.detect_status === 'done').length}/${items.length} זוהו`}
                </span>
              </div>
              {detectionBatch.length > 0 && (
                <span className="muted small" role="status">
                  {detectionBatchCompleted}/{detectionBatch.length} הושלמו · {detectionBatchDone} זוהו
                  {detectionBatchFailed > 0 && ` · ${detectionBatchFailed} נכשלו`}
                </span>
              )}
              {running && (
                <div className="bar">
                  <i style={{ width: `${Math.round((Object.values(progress).find((p) => p != null) ?? 0) * 100)}%` }} />
                </div>
              )}
              <div className="row">
                <button
                  className="filter active"
                  disabled={!!running || pendingCount === 0}
                  onClick={() => void startDetection(false)}
                >
                  זהה חיות ({pendingCount})
                </button>
                <button
                  className="filter"
                  disabled={!!running || detectionTargets.length === 0}
                  onClick={() => void startDetection(true, detectionTargets)}
                >
                  {checked.size > 0
                    ? `זהה מחדש את הנבחרים (${checked.size})`
                    : 'זהה מחדש את הנבחר'}
                </button>
              </div>
              <span className="muted small">SpeciesNet · ישראל · CPU</span>
            </div>
            <MediaGrid
              items={items}
              species={topSpecies}
              selectedId={selectedId}
              checked={checked}
              onSelect={setSelectedId}
              onToggleChecked={toggleChecked}
              onSetChecked={(ids) => setChecked(new Set(ids))}
              onDeleted={(id) => {
                setItems((l) => l.filter((m) => m.id !== id))
                setDetections((l) => l.filter((d) => d.media_id !== id))
                setTimeline((t) => t.filter((x) => x.media_id !== id))
                setChecked((s) => {
                  const next = new Set(s)
                  next.delete(id)
                  return next
                })
                if (id === selectedId) setSelectedId(null)
              }}
            />
          </aside>

          <div className="center">
            <section className="panel">
              <div className="row between">
                <h2>תצוגה מקדימה</h2>
                <div className="segmented">
                  <span className="seg disabled">המיקס הערוך</span>
                  <span className="seg active">מקור</span>
                </div>
              </div>
              <Preview item={selected} detections={detections} seek={seek} />
            </section>
            <DetectionsPanel
              detections={detections}
              items={items}
              onChanged={() => project && void refresh(project.id)}
              onOpen={(id, time) => {
                setSelectedId(id)
                if (time != null) setSeek((s) => ({ time, n: (s?.n ?? 0) + 1 }))
              }}
            />
            <TimelinePanel
              media={items}
              timeline={timeline}
              length={length}
              note={note}
              canAddSelected={!!selected}
              onChange={setTimeline}
              onAddSelected={addSelected}
              onOpen={(id, time) => {
                setSelectedId(id)
                setSeek((s) => ({ time, n: (s?.n ?? 0) + 1 }))
              }}
            />
            <SoundtrackPanel />
          </div>

          <SettingsPanel
            length={length}
            onLength={setLength}
            captions={captions}
            onCaptions={setCaptions}
            openingTitle={openingTitle}
            onOpeningTitle={setOpeningTitle}
            openingTitleSeconds={openingTitleSeconds}
            onOpeningTitleSeconds={setOpeningTitleSeconds}
            closingTitle={closingTitle}
            onClosingTitle={setClosingTitle}
            closingTitleSeconds={closingTitleSeconds}
            onClosingTitleSeconds={setClosingTitleSeconds}
            transition={transition}
            onTransition={setTransition}
          />
        </main>
        )}

        <footer className="foot muted small">
          <span>FRAME Studio</span>
          <span>H.264 / AAC</span>
        </footer>
      </div>
    </div>
  )
}

export default App
