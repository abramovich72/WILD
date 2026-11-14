import { useState } from 'react'
import { api, type MediaItem, type TimelineItem } from '../api'
import { formatDuration } from '../format'

const MIN_PIECE = 0.2
const PAD = 1
const IMAGE_SECONDS = 3
const DET_MIME = 'application/x-wild-detection'
const CLIP_MIME = 'application/x-wild-clip'
const sec = (n: number) => `${n.toFixed(1)} שנ׳`
const uid = () => Math.random().toString(36).slice(2)

const TICK_STEPS = [1, 2, 5, 10, 15, 30, 60, 120, 300]

// Proportional bar: one segment per timeline item, with second marks and the target length.
function SecondsRuler({
  timeline,
  length,
  selUid,
}: {
  timeline: TimelineItem[]
  length: number
  selUid: string | null
}) {
  const total = timeline.reduce((sum, t) => sum + (t.end - t.start), 0)
  const span = Math.max(total, length)
  const step = TICK_STEPS.find((s) => span / s <= 12) ?? 600
  const ticks = Array.from({ length: Math.floor(span / step) + 1 }, (_, i) => i * step)
  const pct = (s: number) => `${(s / span) * 100}%`
  const starts = timeline.map((_, i) =>
    timeline.slice(0, i).reduce((sum, t) => sum + (t.end - t.start), 0),
  )

  return (
    <div className="ruler" aria-label="ציר שניות">
      <div className="ruler-bar">
        {timeline.map((t, i) => {
          const d = t.end - t.start
          const left = starts[i]
          return (
            <span
              key={t.uid}
              className={`ruler-seg${i % 2 ? ' alt' : ''}${t.uid === selUid ? ' sel' : ''}`}
              style={{ insetInlineStart: pct(left), width: pct(d) }}
              title={`${i + 1}. ${t.label ?? ''} · ${sec(left)}–${sec(left + d)}`}
            >
              {i + 1}
            </span>
          )
        })}
        <span className="ruler-goal" style={{ insetInlineStart: pct(length) }} title={`אורך יעד: ${length} שנ׳`} />
      </div>
      <div className="ruler-ticks">
        {ticks.map((s) => (
          <span key={s} style={{ insetInlineStart: pct(s) }}>
            <i />
            {s}
          </span>
        ))}
      </div>
    </div>
  )
}

type Props = {
  media: MediaItem[]
  timeline: TimelineItem[]
  length: number
  note: string
  canAddSelected: boolean
  onChange: (t: TimelineItem[]) => void
  onAddSelected: () => void
  onOpen: (mediaId: number, time: number) => void
}

export function TimelinePanel({
  media,
  timeline,
  length,
  note,
  canAddSelected,
  onChange,
  onAddSelected,
  onOpen,
}: Props) {
  const [selUid, setSelUid] = useState<string | null>(null)
  const [dragUid, setDragUid] = useState<string | null>(null)
  const [hover, setHover] = useState(false)
  const [overUid, setOverUid] = useState<string | null>(null)
  const byId = new Map(media.map((m) => [m.id, m]))
  const total = timeline.reduce((sum, t) => sum + (t.end - t.start), 0)
  const overTarget = total > length + 0.05
  const sel = timeline.find((t) => t.uid === selUid) ?? null
  const selMedia = sel ? byId.get(sel.media_id) : undefined

  function update(uid: string, patch: Partial<TimelineItem>) {
    onChange(timeline.map((t) => (t.uid === uid ? { ...t, ...patch } : t)))
  }

  function move(uid: string, to: number) {
    const from = timeline.findIndex((t) => t.uid === uid)
    if (from < 0 || to < 0 || to >= timeline.length || from === to) return
    const next = [...timeline]
    next.splice(to, 0, next.splice(from, 1)[0])
    onChange(next)
  }

  // Handles both reordering an existing card and dropping a detection dragged in
  // from the "found animals" panel. `index` is the insert position (default: end).
  function drop(e: React.DragEvent, index = timeline.length) {
    e.preventDefault()
    e.stopPropagation()
    setHover(false)
    setOverUid(null)
    const raw = e.dataTransfer.getData(DET_MIME)
    if (!raw) {
      const moving = e.dataTransfer.getData(CLIP_MIME) || dragUid
      if (moving) move(moving, Math.min(index, timeline.length - 1))
      setDragUid(null)
      return
    }
    const d: { media_id: number; start: number | null; end: number | null; label: string | null } =
      JSON.parse(raw)
    const m = byId.get(d.media_id)
    if (!m) return
    let start = 0
    let end = IMAGE_SECONDS
    if (m.kind === 'video') {
      const dur = m.duration ?? d.end ?? 0
      start = Math.max(0, (d.start ?? 0) - PAD)
      end = Math.min(dur, (d.end ?? dur) + PAD)
      if (end - start < MIN_PIECE) return
    }
    const round = (n: number) => Math.round(n * 100) / 100
    const next = [...timeline]
    next.splice(index, 0, {
      uid: uid(),
      media_id: d.media_id,
      start: round(start),
      end: round(end),
      label: d.label,
    })
    onChange(next)
  }

  function commitStart(v: number) {
    if (!sel || !selMedia || Number.isNaN(v)) return
    const max = sel.end - MIN_PIECE
    update(sel.uid, { start: Math.min(Math.max(0, v), max) })
  }

  function commitEnd(v: number) {
    if (!sel || !selMedia || Number.isNaN(v)) return
    const cap = selMedia.duration ?? Infinity
    update(sel.uid, { end: Math.min(Math.max(sel.start + MIN_PIECE, v), cap) })
  }

  return (
    <section className="panel">
      <div className="row between">
        <h3>ציר הזמן</h3>
        <span
          className={`timeline-duration small ${overTarget ? 'over' : 'muted'}`}
          role={overTarget ? 'status' : undefined}
        >
          משך הציר: {sec(total)} · אורך יעד: {length} שנ׳
          {overTarget && <> · אזהרה: חריגה של {sec(total - length)}</>}
        </span>
      </div>

      <div className="tl-actions">
        <button className="filter" disabled={!canAddSelected} onClick={onAddSelected}>
          + הוסף את הנבחר
        </button>
        <button className="filter" disabled={timeline.length === 0} onClick={() => onChange([])}>
          נקה
        </button>
      </div>
      {note && <p className="small muted">{note}</p>}

      <div
        className={`tl-drop${hover ? ' over-drop' : ''}`}
        onDragOver={(e) => {
          e.preventDefault()
          setHover(true)
        }}
        onDragLeave={() => setHover(false)}
        onDrop={(e) => drop(e)}
      >
        {timeline.length === 0 ? (
          <p className="muted small">גררו לכאן סרטונים ותמונות מהספרייה, או זיהויים מהחלונית ״מצאתי חיות״.</p>
        ) : (
          <div className="timeline-strip">
            {timeline.map((t, i) => {
              const m = byId.get(t.media_id)
              return (
                <div
                  key={t.uid}
                  className={`clip${t.uid === selUid ? ' selected' : ''}${t.uid === dragUid ? ' dragging' : ''}${t.uid === overUid && t.uid !== dragUid ? ' drop-target' : ''}`}
                  draggable
                  onDragStart={(e) => {
                    e.dataTransfer.effectAllowed = 'move'
                    e.dataTransfer.setData(CLIP_MIME, t.uid)
                    // Deferred so the browser captures the drag image before the style changes.
                    setTimeout(() => setDragUid(t.uid), 0)
                  }}
                  onDragOver={(e) => {
                    e.preventDefault()
                    e.stopPropagation()
                    setOverUid(t.uid)
                  }}
                  onDrop={(e) => drop(e, i)}
                  onDragEnd={() => {
                    setDragUid(null)
                    setOverUid(null)
                  }}
                  onClick={() => {
                    setSelUid(t.uid)
                    onOpen(t.media_id, t.start)
                  }}
                  title={m?.filename}
                >
                  {m?.thumb_name ? (
                    <img src={api.thumbUrl(m.id)} alt="" draggable={false} />
                  ) : (
                    <div className="nothumb" />
                  )}
                  <span className="clip-dur">{t.end - t.start < 10 ? sec(t.end - t.start) : formatDuration(t.end - t.start)}</span>
                  {t.label && <span className="clip-label">{t.label}</span>}
                  <button
                    className="clip-x"
                    aria-label="הסרה מהציר"
                    onClick={(e) => {
                      e.stopPropagation()
                      onChange(timeline.filter((x) => x.uid !== t.uid))
                    }}
                  >
                    ✕
                  </button>
                </div>
              )
            })}
          </div>
        )}
      </div>

      {timeline.length > 0 && <SecondsRuler timeline={timeline} length={length} selUid={selUid} />}

      {sel && selMedia && (
        <div className="trim row">
          <strong className="small">{selMedia.filename}</strong>
          {selMedia.kind === 'video' ? (
            <>
              <label className="small">
                התחלה
                <input
                  key={`s${sel.uid}${sel.start}`}
                  type="number"
                  step="0.1"
                  min={0}
                  defaultValue={sel.start}
                  onBlur={(e) => commitStart(e.target.valueAsNumber)}
                  onKeyDown={(e) => e.key === 'Enter' && e.currentTarget.blur()}
                />
              </label>
              <label className="small">
                סיום
                <input
                  key={`e${sel.uid}${sel.end}`}
                  type="number"
                  step="0.1"
                  max={selMedia.duration ?? undefined}
                  defaultValue={sel.end}
                  onBlur={(e) => commitEnd(e.target.valueAsNumber)}
                  onKeyDown={(e) => e.key === 'Enter' && e.currentTarget.blur()}
                />
              </label>
            </>
          ) : (
            <label className="small">
              משך תצוגה
              <input
                key={`d${sel.uid}${sel.end}`}
                type="number"
                step="0.5"
                min={0.5}
                max={60}
                defaultValue={sel.end}
                onBlur={(e) => {
                  const v = e.target.valueAsNumber
                  if (!Number.isNaN(v)) update(sel.uid, { start: 0, end: Math.min(60, Math.max(0.5, v)) })
                }}
                onKeyDown={(e) => e.key === 'Enter' && e.currentTarget.blur()}
              />
            </label>
          )}
          <button
            className="icon"
            aria-label="הזז קדימה"
            onClick={() => move(sel.uid, timeline.findIndex((t) => t.uid === sel.uid) - 1)}
          >
            ▶
          </button>
          <button
            className="icon"
            aria-label="הזז אחורה"
            onClick={() => move(sel.uid, timeline.findIndex((t) => t.uid === sel.uid) + 1)}
          >
            ◀
          </button>
        </div>
      )}
    </section>
  )
}
