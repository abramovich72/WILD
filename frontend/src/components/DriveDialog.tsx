import { useCallback, useEffect, useRef, useState } from 'react'
import { drive, type DriveImportJob, type DriveItem, type DriveStatus } from '../api'
import { formatSize } from '../format'

type Crumb = { id: string; name: string; key?: string | null }
const ROOT: Crumb = { id: 'root', name: 'ה-Drive שלי' }
const SHARED: Crumb = { id: 'shared', name: 'שותפו איתי' }
const ICON = { folder: '📁', image: '🖼', video: '🎞', other: '' }

export function DriveDialog({
  projectId,
  open,
  onOpen,
  onImported,
  onClose,
}: {
  projectId: number
  open: boolean
  onOpen: () => void
  onImported: () => void
  onClose: () => void
}) {
  const [status, setStatus] = useState<DriveStatus | null>(null)
  const [path, setPath] = useState<Crumb[]>([ROOT])
  const [items, setItems] = useState<DriveItem[]>([])
  const [next, setNext] = useState<string | null>(null)
  const [selected, setSelected] = useState<Map<string, DriveItem>>(new Map())
  const [link, setLink] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [imported, setImported] = useState<Set<string>>(new Set())
  const [job, setJob] = useState<DriveImportJob | null>(null)
  const [activeJobLoaded, setActiveJobLoaded] = useState(false)
  const [recursive, setRecursive] = useState(false)
  const [dismissedJobId, setDismissedJobId] = useState<string | null>(null)

  const here = path[path.length - 1]
  const running = job?.status === 'queued' || job?.status === 'running'
  const cancelling = job?.phase === 'מבטל הורדה…'
  const jobId = job?.id
  const onImportedRef = useRef(onImported)
  const mounted = useRef(true)
  const wasOpen = useRef(open)
  const lastDone = useRef(0)
  useEffect(() => {
    onImportedRef.current = onImported
  })

  useEffect(() => {
    if (wasOpen.current && !open) setSelected(new Map())
    wasOpen.current = open
  }, [open])

  const load = useCallback(async (crumb: Crumb, token?: string | null) => {
    setLoading(true)
    setError('')
    try {
      const r = await drive.files(crumb.id, token, crumb.key)
      setItems((old) => (token ? [...old, ...r.items] : r.items))
      setNext(r.next_page_token)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'שגיאה')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    mounted.current = true
    drive
      .status()
      .then((s) => {
        if (!mounted.current) return
        setStatus(s)
        if (s.connected) {
          void load(ROOT)
          void drive.imported(projectId).then((ids) => setImported(new Set(ids)))
        }
        if (s.enabled) {
          void drive.activeImport().then((j) => {
            if (!mounted.current || !j) return
            setJob(j)
            setDismissedJobId(null)
            lastDone.current = j.done
            onImportedRef.current()
          })
            .catch((e: Error) => {
              if (mounted.current) setError(e.message)
            })
            .finally(() => {
              if (mounted.current) setActiveJobLoaded(true)
            })
        } else {
          setActiveJobLoaded(true)
        }
      })
      .catch((e: Error) => {
        if (mounted.current) setError(e.message)
      })
    return () => {
      mounted.current = false
    }
  }, [load, projectId])

  useEffect(() => {
    if (!jobId || !running) return
    const t = setInterval(() => {
      drive
        .importJob(jobId)
        .then((j) => {
          setJob(j)
          if (j.done !== lastDone.current || j.status === 'done') {
            lastDone.current = j.done
            onImportedRef.current()
          }
          if (j.status === 'done' || j.status === 'failed' || j.status === 'cancelled') {
            void drive.imported(j.project_id).then((ids) => setImported(new Set(ids)))
          }
        })
        .catch((e: Error) => setError(e.message))
    }, 1000)
    return () => clearInterval(t)
  }, [jobId, running, projectId])

  async function startImport() {
    setError('')
    try {
      const newJob = await drive.startImport(projectId, [...selected.values()], recursive)
      setJob(newJob)
      setDismissedJobId(null)
      lastDone.current = newJob.done
      setSelected(new Map())
    } catch (e) {
      setError(e instanceof Error ? e.message : 'שגיאה')
    }
  }

  async function cancelImport() {
    if (!job || !running || cancelling) return
    setError('')
    try {
      setJob(await drive.cancelImport(job.id))
    } catch (e) {
      setError(e instanceof Error ? e.message : 'שגיאה')
    }
  }

  function dismissJob() {
    if (job && !running) setDismissedJobId(job.id)
  }

  function selectAllHere() {
    setSelected((s) => {
      const nextSel = new Map(s)
      for (const it of items) if (it.kind !== 'folder' && !imported.has(it.id)) nextSel.set(it.id, it)
      return nextSel
    })
  }

  function go(next: Crumb[]) {
    setSelected(new Map())
    setPath(next)
    void load(next[next.length - 1])
  }

  async function login() {
    try {
      window.location.href = (await drive.authUrl()).url
    } catch (e) {
      setError(e instanceof Error ? e.message : 'שגיאה')
    }
  }

  async function logout() {
    await drive.logout()
    setStatus({ enabled: true, configured: true, connected: false, email: null })
    setItems([])
    setSelected(new Map())
  }

  async function openLink() {
    setError('')
    try {
      const item = await drive.resolve(link)
      if (item.kind === 'folder') {
        go([{ id: item.id, name: item.name, key: item.resource_key }])
      } else {
        setSelected(new Map([[item.id, item]]))
      }
      setLink('')
    } catch (e) {
      setError(e instanceof Error ? e.message : 'שגיאה')
    }
  }

  const toggle = (it: DriveItem) =>
    setSelected((s) => {
      const nextSel = new Map(s)
      if (!nextSel.delete(it.id)) nextSel.set(it.id, it)
      return nextSel
    })

  const enter = (it: DriveItem) => go([...path, { id: it.id, name: it.name, key: it.resource_key }])

  return (
    <>
    {open && <div className="modal-back" onClick={onClose}>
      <div className="modal" role="dialog" aria-label="ייבוא מ-Google Drive" onClick={(e) => e.stopPropagation()}>
        <div className="row between">
          <h2>ייבוא מ-Google Drive</h2>
          <button className="icon" aria-label="סגירה" onClick={onClose}>
            ✕
          </button>
        </div>

        {status && !status.enabled && (
          <p className="muted small">ייבוא מ-Google Drive כבוי בהגדרות השרת.</p>
        )}

        {status?.enabled && !status.configured && (
          <p className="error small">
            החיבור ל-Google לא הוגדר. יש להוסיף GOOGLE_CLIENT_ID ו-GOOGLE_CLIENT_SECRET לקובץ
            backend\.env ולהפעיל מחדש את השרת.
          </p>
        )}

        {status?.enabled && status.configured && !status.connected && (
          <div className="drive-login">
            <p className="muted small">התחברו לחשבון Google כדי לדפדף בקבצים (הרשאת קריאה בלבד).</p>
            <button className="primary" onClick={() => void login()}>
              התחברות עם Google
            </button>
          </div>
        )}

        {status?.enabled && status.connected && (
          <>
            <div className="row between small">
              <span className="muted" dir="ltr">
                {status.email}
              </span>
              <button className="filter" disabled={running} onClick={() => void logout()}>
                התנתקות
              </button>
            </div>

            <div className="drive-link row">
              <input
                dir="ltr"
                placeholder="הדביקו קישור לתיקייה או קובץ ב-Drive"
                value={link}
                onChange={(e) => setLink(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && link.trim() && void openLink()}
              />
              <button className="filter" disabled={!link.trim()} onClick={() => void openLink()}>
                פתח
              </button>
            </div>

            <div className="filters">
              <button className={`filter${path[0].id === 'root' ? ' active' : ''}`} onClick={() => go([ROOT])}>
                {ROOT.name}
              </button>
              <button className={`filter${path[0].id === 'shared' ? ' active' : ''}`} onClick={() => go([SHARED])}>
                {SHARED.name}
              </button>
            </div>

            <nav className="crumbs small">
              {path.map((c, i) => (
                <span key={`${c.id}-${i}`}>
                  {i > 0 && ' / '}
                  <button className="linklike" onClick={() => go(path.slice(0, i + 1))}>
                    {c.name}
                  </button>
                </span>
              ))}
            </nav>

            <ul className="drive-list">
              {items.map((it) => (
                <li key={it.id} className="drive-row">
                  <label className="drive-main">
                    <input
                      type="checkbox"
                      checked={selected.has(it.id)}
                      disabled={running || !activeJobLoaded || imported.has(it.id)}
                      onChange={() => toggle(it)}
                    />
                    <span>{ICON[it.kind]}</span>{' '}
                    {it.kind === 'folder' ? <strong dir="auto">{it.name}</strong> : <span dir="auto">{it.name}</span>}
                    {it.size != null && <span className="muted small">{formatSize(it.size)}</span>}
                    {imported.has(it.id) && <span className="muted small">✓ כבר יובא</span>}
                  </label>
                  {it.kind === 'folder' && (
                    <button className="filter" onClick={() => enter(it)}>
                      פתח
                    </button>
                  )}
                </li>
              ))}
              {!loading && items.length === 0 && !error && <li className="muted small">אין תמונות, סרטונים או תיקיות כאן.</li>}
            </ul>
            {next && (
              <button className="filter" disabled={loading} onClick={() => void load(here, next)}>
                טען עוד
              </button>
            )}
            {loading && <p className="muted small">טוען…</p>}

            {job && (
              <div className="small drive-job" role="status" aria-live="polite">
                {running ? (
                  <>
                    <div className="drive-job-heading">
                      <span className="drive-spinner" aria-hidden="true" />
                      <span>
                        {job.phase}
                        {job.current ? `: ${job.current}` : ''}
                      </span>
                    </div>
                    <button className="filter" disabled={cancelling} onClick={() => void cancelImport()}>
                      {cancelling ? 'מבטל…' : 'הפסק הורדה'}
                    </button>
                    <progress
                      className="drive-progress"
                      max={job.total || 1}
                      value={job.total ? job.done : undefined}
                    />
                    <span className="muted">
                      {job.done}/{job.total || '…'} קבצים · הורדו {formatSize(job.bytes_done)}
                    </span>
                  </>
                ) : job.status === 'cancelled' ? (
                  <div>ההורדה בוטלה: יובאו {job.done}, דולגו {job.skipped}, נכשלו {job.failed}</div>
                ) : job.status === 'failed' ? (
                  <div>הייבוא נכשל: יובאו {job.done}, דולגו {job.skipped}, נכשלו {job.failed}</div>
                ) : (
                  <div>
                    הסתיים: יובאו {job.done}, דולגו (כבר יובאו) {job.skipped}, נכשלו {job.failed}
                  </div>
                )}
                {job.errors.map((e, i) => (
                  <div key={i} className="error">
                    {e.name}: {e.error}
                  </div>
                ))}
              </div>
            )}

            <div className="row between drive-foot">
              <span className="small muted">
                {selected.size} נבחרו בתיקייה הנוכחית
                <button
                  className="linklike"
                  disabled={selected.size === 0 || running}
                  onClick={() => setSelected(new Map())}
                >
                  נקה בחירה
                </button>
                <label className="row">
                  <input
                    type="checkbox"
                    checked={recursive}
                    disabled={running || !activeJobLoaded}
                    onChange={(e) => setRecursive(e.target.checked)}
                  />
                  כולל תתי-תיקיות
                </label>
              </span>
              <span className="row">
                <button className="filter" disabled={running || !activeJobLoaded || !items.some((i) => i.kind !== 'folder')} onClick={selectAllHere}>
                  בחר את כל הקבצים כאן
                </button>
                <button className="primary" disabled={running || !activeJobLoaded || selected.size === 0} onClick={() => void startImport()}>
                  ייבוא
                </button>
              </span>
            </div>
          </>
        )}

        {error && <p className="error small">{error}</p>}
      </div>
    </div>}
    {!open && job && dismissedJobId !== job.id && (
      <div className="drive-import-toast small" role="status" aria-live="polite">
        {running ? (
          <>
            <div className="drive-job-heading">
              <span className="drive-spinner" aria-hidden="true" />
              <strong>ייבוא מ-Drive נמשך</strong>
            </div>
            <span>{job.phase}{job.current ? `: ${job.current}` : ''}</span>
            <progress
              className="drive-progress"
              max={job.total || 1}
              value={job.total ? job.done : undefined}
            />
            <span className="muted">
              {job.done}/{job.total || '…'} קבצים · הורדו {formatSize(job.bytes_done)}
            </span>
            <div className="row between">
              <button className="linklike" onClick={onOpen}>הצג חלונית</button>
              <button className="filter" disabled={cancelling} onClick={() => void cancelImport()}>
                {cancelling ? 'מבטל…' : 'הפסק הורדה'}
              </button>
            </div>
          </>
        ) : (
          <>
            <strong>
              {job.status === 'cancelled'
                ? 'ייבוא מ-Drive בוטל'
                : job.status === 'failed'
                  ? 'ייבוא מ-Drive נכשל'
                  : 'ייבוא מ-Drive הסתיים'}
            </strong>
            <span>יובאו {job.done}, דולגו {job.skipped}, נכשלו {job.failed}</span>
            <div className="row between">
              <button className="linklike" onClick={onOpen}>הצג פרטים</button>
              <button className="icon" aria-label="סגירת הודעת הייבוא" onClick={dismissJob}>✕</button>
            </div>
          </>
        )}
      </div>
    )}
    </>
  )
}
