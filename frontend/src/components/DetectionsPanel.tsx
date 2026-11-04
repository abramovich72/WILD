import { useState } from 'react'
import { api, type Detection, type MediaItem } from '../api'
import { formatDuration } from '../format'

type Props = {
  detections: Detection[]
  items: MediaItem[]
  onOpen: (mediaId: number, time: number | null) => void
  onChanged: () => void
}

export function DetectionsPanel({ detections, items, onOpen, onChanged }: Props) {
  const [species, setSpecies] = useState<string | null>(null)
  const [collapsed, setCollapsed] = useState(() => localStorage.getItem('detections-collapsed') === '1')
  const names = new Map(items.map((m) => [m.id, m.filename]))
  const counts = new Map<string, number>()
  for (const d of detections) counts.set(d.display, (counts.get(d.display) ?? 0) + 1)
  const shown = detections.filter((d) => !species || d.display === species)

  function toggle() {
    setCollapsed((c) => {
      localStorage.setItem('detections-collapsed', c ? '0' : '1')
      return !c
    })
  }

  async function rename(d: Detection) {
    const next = prompt('שם המין (באנגלית, כמו ב-SpeciesNet):', d.species)
    if (!next?.trim() || next.trim() === d.species) return
    await api.correctDetection(d.id, next.trim())
    onChanged()
  }

  return (
    <section className="panel">
      <button className="row between collapse-head" onClick={toggle} aria-expanded={!collapsed}>
        <h3>
          <span className="chevron">{collapsed ? '◀' : '▼'}</span> מצאתי חיות
        </h3>
        <span className="muted small">{detections.length} זיהויים</span>
      </button>
      {collapsed ? null : detections.length === 0 ? (
        <p className="muted small">אין זיהויים עדיין. לחצו על ״זהה חיות״ בפאנל המדיה.</p>
      ) : (
        <>
          <div className="chips">
            <button className={`filter${!species ? ' active' : ''}`} onClick={() => setSpecies(null)}>
              הכל
            </button>
            {[...counts].map(([name, n]) => (
              <button
                key={name}
                className={`filter${species === name ? ' active' : ''}`}
                onClick={() => setSpecies(name)}
              >
                {name} · {n}
              </button>
            ))}
          </div>
          <p className="muted small">גררו זיהויים לציר הזמן כדי להוסיף אותם.</p>
          <ul className="det-list">
            {shown.map((d) => (
              <li
                key={d.id}
                className="det"
                draggable
                onDragStart={(e) => {
                  e.dataTransfer.effectAllowed = 'copy'
                  e.dataTransfer.setData(
                    'application/x-wild-detection',
                    JSON.stringify({
                      media_id: d.media_id,
                      start: d.start_time,
                      end: d.end_time,
                      label: d.display,
                    }),
                  )
                }}
              >
                <button className="det-main" onClick={() => onOpen(d.media_id, d.start_time)}>
                  <strong>{d.display}</strong>
                  {d.corrected && <span className="soon">תוקן</span>}
                  <span className="muted small" dir="ltr">
                    {names.get(d.media_id) ?? ''}
                    {d.start_time != null &&
                      ` · ${formatDuration(d.start_time)}–${formatDuration(d.end_time)}`}
                    {` · ${Math.round(d.confidence * 100)}%`}
                  </span>
                </button>
                <button className="icon" aria-label="תיקון מין" onClick={() => void rename(d)}>
                  ✎
                </button>
                <button
                  className="icon"
                  aria-label="מחיקת זיהוי"
                  onClick={async () => {
                    await api.deleteDetection(d.id)
                    onChanged()
                  }}
                >
                  ✕
                </button>
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  )
}
