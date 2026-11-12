import { useEffect, useMemo, useRef, useState } from 'react'
import {
  api,
  type Clip,
  type DetectProgress,
  type Detection,
  type MediaItem,
  type MusicStyle,
  type Project,
  type TimelineItem,
  type Transition,
} from './api'
import { ClipsPanel } from './components/ClipsPanel'
import { DetectionsPanel } from './components/DetectionsPanel'
import { DetectionEditor } from './components/DetectionEditor'
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
const activeProjectKey = 'wild.activeProjectId'

function App() {
  const [projects, setProjects] = useState<Project[]>([])
  const [projectsLoaded, setProjectsLoaded] = useState(false)
  const [project, setProject] = useState<Project | null>(null)
  const [projectLoading, setProjectLoading] = useState(false)
  const [projectError, setProjectError] = useState('')
  const [newProjectName, setNewProjectName] = useState('')
  const [creatingProject, setCreatingProject] = useState(false)
  const [items, setItems] = useState<MediaItem[]>([])
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [checked, setChecked] = useState<Set<number>>(new Set())
  const [length, setLength] = useState(30)
  const [editing, setEditing] = useState(false)
  const [activeTab, setActiveTab] = useState<'edit' | 'outputs'>('edit')
  const [error, setError] = useState('')
  const [detections, setDetections] = useState<Detection[]>([])
  const [detectionEditor, setDetectionEditor] = useState<{ detection: Detection | null } | null>(null)
  const [previewTime, setPreviewTime] = useState(0)
  const [progress, setProgress] = useState<Record<number, number | null>>({})
  const [seek, setSeek] = useState<{ time: number; n: number } | null>(null)
  const [timeline, setTimeline] = useState<TimelineItem[]>([])
  const [captions, setCaptions] = useState(true)
  const [openingTitle, setOpeningTitle] = useState('')
  const [openingTitleSeconds, setOpeningTitleSeconds] = useState(3)
  const [closingTitle, setClosingTitle] = useState('')
  const [closingTitleSeconds, setClosingTitleSeconds] = useState(3)
  const [transition, setTransition] = useState<Transition>('fade')
  const [musicEnabled, setMusicEnabled] = useState(false)
  const [musicPrompt, setMusicPrompt] = useState(
    'Calm instrumental music for a nature documentary, gentle strings and piano',
  )
  const [musicStyle, setMusicStyle] = useState<MusicStyle>('ambient')
  const [musicVolume, setMusicVolume] = useState(75)
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
      await api.detect(project.id, { media_ids: ids, force })
      listen(project.id)
    } catch {
      setError('לא ניתן להתחבר לשרת')
    }
  }

  useEffect(() => {
    let cancelled = false
    void api
      .projects()
      .then(async (list) => {
        if (cancelled) return
        setProjects(list)
        const savedProjectId = localStorage.getItem(activeProjectKey)
        const savedProject = list.find((item) => String(item.id) === savedProjectId)
        if (savedProject) {
          await openProject(savedProject)
        } else if (savedProjectId !== null) {
          localStorage.removeItem(activeProjectKey)
        }
      })
      .catch(() => {
        if (!cancelled) setError('לא ניתן להתחבר לשרת')
      })
      .finally(() => {
        if (!cancelled) setProjectsLoaded(true)
      })
    return () => {
      cancelled = true
      source.current?.close()
      source.current = null
    }
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

  async function openProject(next: Project) {
    source.current?.close()
    source.current = null
    timelineLoaded.current = false
    setProject(null)
    setProjectLoading(true)
    setProjectError('')
    setItems([])
    setDetections([])
    setClips([])
    setTimeline([])
    setSelectedId(null)
    setChecked(new Set())
    setProgress({})
    setSeek(null)
    setDetectionEditor(null)
    setEditing(false)
    setActiveTab('edit')
    setNote('')
    setShowDrive(false)

    try {
      const [media, dets, projectClips] = await Promise.all([
        api.media(next.id),
        api.detections(next.id),
        api.clips(next.id),
      ])
      let saved: TimelineItem[] = []
      try {
        saved = JSON.parse(localStorage.getItem(timelineKey(next.id)) ?? '[]')
      } catch {
        saved = []
      }
      const mediaIds = new Set(media.map((m) => m.id))
      setItems(media)
      setDetections(dets)
      setClips(projectClips)
      setTimeline(saved.filter((item) => mediaIds.has(item.media_id)))
      setProject(next)
      localStorage.setItem(activeProjectKey, String(next.id))
      timelineLoaded.current = true
      if (media.some((m) => m.detect_status === 'queued' || m.detect_status === 'running'))
        listen(next.id)
    } catch {
      setProjectError('לא ניתן לטעון את הפרויקט')
    } finally {
      setProjectLoading(false)
    }
  }

  function showProjects() {
    source.current?.close()
    source.current = null
    timelineLoaded.current = false
    setProject(null)
    setItems([])
    setDetections([])
    setClips([])
    setTimeline([])
    setSelectedId(null)
    setChecked(new Set())
    setProgress({})
    setSeek(null)
    setDetectionEditor(null)
    setEditing(false)
    setActiveTab('edit')
    setNote('')
    setShowDrive(false)
    setProjectError('')
  }

  async function createProject() {
    const name = newProjectName.trim()
    if (!name) {
      setProjectError('יש להזין שם לפרויקט')
      return
    }
    setCreatingProject(true)
    setProjectError('')
    try {
      const created = await api.createProject(name)
      setProjects((list) => [...list, created])
      setNewProjectName('')
      await openProject(created)
    } catch {
      setProjectError('לא ניתן ליצור את הפרויקט')
    } finally {
      setCreatingProject(false)
    }
  }

  const topSpecies = useMemo(() => {
    const best = new Map<number, Detection>()
    for (const d of detections) {
      const cur = best.get(d.media_id)
      const priority = (item: Detection) =>
        item.source === 'manual' ? 2 : item.corrected ? 1 : 0
      if (
        !cur ||
        priority(d) > priority(cur) ||
        (priority(d) === priority(cur) && d.confidence > cur.confidence)
      )
        best.set(d.media_id, d)
    }
    return new Map([...best].map(([id, d]) => [id, d.display]))
  }, [detections])

  if (error) return <p className="error page">{error}</p>
  if (!projectsLoaded) return <p className="muted page">טוען פרויקטים…</p>
  if (projectLoading) return <p className="muted page">טוען פרויקט…</p>

  if (!project) {
    return (
      <div className="app">
        <div className="page">
          <header className="head">
            <div className="title-block">
              <img className="brand-logo" src="/wild-clips-logo.png" alt="WILD Clips" />
              <div>
                <div className="breadcrumb">ניהול פרויקטים</div>
                <h1>בחירת פרויקט</h1>
              </div>
            </div>
          </header>
          <main className="projects-home">
            <section className="panel">
              <div className="project-home-intro">
                <h2>הפרויקטים שלך</h2>
                <p className="muted small">בחר פרויקט כדי לנהל את הקבצים והתוצרים שלו.</p>
              </div>
              <form
                className="project-create"
                onSubmit={(event) => {
                  event.preventDefault()
                  void createProject()
                }}
              >
                <label htmlFor="new-project-name">יצירת פרויקט חדש</label>
                <div className="project-create-controls">
                  <input
                    id="new-project-name"
                    value={newProjectName}
                    maxLength={120}
                    onChange={(event) => setNewProjectName(event.target.value)}
                    placeholder="שם הפרויקט"
                  />
                  <button className="primary" type="submit" disabled={creatingProject}>
                    {creatingProject ? 'יוצר…' : 'יצירת פרויקט'}
                  </button>
                </div>
              </form>
              {projectError && <p className="error small">{projectError}</p>}
            </section>
            {projects.length === 0 ? (
              <p className="muted center-text">עדיין אין פרויקטים. צור פרויקט כדי להתחיל.</p>
            ) : (
              <section className="project-grid" aria-label="רשימת פרויקטים">
                {projects.map((item) => (
                  <article className="panel project-card" key={item.id}>
                    <div>
                      <h2>{item.name}</h2>
                      <span className="muted small">פרויקט {item.id}</span>
                    </div>
                    <button
                      className="primary"
                      type="button"
                      disabled={projectLoading}
                      onClick={() => void openProject(item)}
                    >
                      פתיחת פרויקט
                    </button>
                  </article>
                ))}
              </section>
            )}
          </main>
        </div>
      </div>
    )
  }

  const selected = items.find((m) => m.id === selectedId) ?? null
  const active = items.filter((m) => m.detect_status === 'queued' || m.detect_status === 'running')
  const running = active.length ? active : null
  const pendingCount = items.filter(
    (m) => m.detect_status === 'pending' || m.detect_status === 'failed',
  ).length
  const detectionTargets = checked.size > 0 ? [...checked] : selected ? [selected.id] : []
  const editorMedia = detectionEditor
    ? items.find(
        (item) => item.id === (detectionEditor.detection?.media_id ?? selectedId),
      ) ?? null
    : null

  async function rename(name: string) {
    setEditing(false)
    if (!project || !name.trim() || name === project.name) return
    const renamed = await api.renameProject(project.id, name)
    setProject(renamed)
    setProjects((list) => list.map((item) => (item.id === renamed.id ? renamed : item)))
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
        music: {
          enabled: musicEnabled,
          prompt: musicPrompt,
          style: musicStyle,
          volume: musicVolume / 100,
        },
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
                {items.length} קבצים
              </div>
            </div>
          </div>
          <div className="head-actions">
            <button className="filter" disabled={rendering} onClick={showProjects}>
              בחירת פרויקט
            </button>
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
                <div className="row">
                  <button
                    className="filter"
                    disabled={!selected}
                    onClick={() => setDetectionEditor({ detection: null })}
                  >
                    + הוסף זיהוי
                  </button>
                  <div className="segmented">
                    <span className="seg disabled">המיקס הערוך</span>
                    <span className="seg active">מקור</span>
                  </div>
                </div>
              </div>
              <Preview
                item={selected}
                detections={detections}
                seek={seek}
                onTimeUpdate={setPreviewTime}
              />
            </section>
            <DetectionsPanel
              detections={detections}
              items={items}
              onChanged={() => project && void refresh(project.id)}
              onEdit={(detection) => setDetectionEditor({ detection })}
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
            musicEnabled={musicEnabled}
            onMusicEnabled={setMusicEnabled}
            musicPrompt={musicPrompt}
            onMusicPrompt={setMusicPrompt}
            musicStyle={musicStyle}
            onMusicStyle={setMusicStyle}
            musicVolume={musicVolume}
            onMusicVolume={setMusicVolume}
          />
        </main>
        )}

        {detectionEditor && editorMedia && (
          <DetectionEditor
            item={editorMedia}
            detection={detectionEditor.detection}
            initialTime={previewTime}
            onClose={() => setDetectionEditor(null)}
            onSaved={() => {
              setDetectionEditor(null)
              void refresh(project.id)
            }}
          />
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
