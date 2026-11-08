import { useState } from 'react'
import { api, type Detection, type MediaItem } from '../api'
import { formatDuration } from '../format'

const COMMON_SPECIES_LIMIT = 6

type Props = {
  detections: Detection[]
  items: MediaItem[]
  onOpen: (mediaId: number, time: number | null) => void
  onEdit: (detection: Detection) => void
  onChanged: () => void
}

export function DetectionsPanel({ detections, items, onOpen, onEdit, onChanged }: Props) {
  const [species, setSpecies] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [showAllSpecies, setShowAllSpecies] = useState(false)
  const [collapsed, setCollapsed] = useState(() => localStorage.getItem('detections-collapsed') === '1')
  const names = new Map(items.map((m) => [m.id, m.filename]))
  const counts = new Map<string, number>()
  for (const d of detections) counts.set(d.display, (counts.get(d.display) ?? 0) + 1)
  const sortedCounts = [...counts].sort(
    ([a, countA], [b, countB]) => countB - countA || a.localeCompare(b, 'he'),
  )
  const query = search.trim().toLocaleLowerCase()
  const matchingCounts = sortedCounts.filter(([name]) =>
    name.toLocaleLowerCase().includes(query),
  )
  const visibleCounts: [string, number][] =
    query || showAllSpecies ? matchingCounts : sortedCounts.slice(0, COMMON_SPECIES_LIMIT)
  const selectedCount = species && !query ? sortedCounts.find(([name]) => name === species) : null
  if (selectedCount && !visibleCounts.some(([name]) => name === species)) {
    visibleCounts.push(selectedCount)
  }
  const shown = detections.filter(
    (d) =>
      (!species || d.display === species) &&
      (!query || d.display.toLocaleLowerCase().includes(query)),
  )

  function toggle() {
    setCollapsed((c) => {
      localStorage.setItem('detections-collapsed', c ? '0' : '1')
      return !c
    })
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
          <div className="det-controls">
            <input
              className="det-search"
              type="search"
              aria-label="חיפוש זיהויים"
              placeholder="חיפוש מין או משפחה…"
              value={search}
              onChange={(e) => {
                setSearch(e.target.value)
                setSpecies(null)
              }}
            />
            <div className={`chips det-filter-chips${query || showAllSpecies ? ' expanded' : ''}`}>
              <button
                className={`filter${!species && !query ? ' active' : ''}`}
                onClick={() => {
                  setSpecies(null)
                  setSearch('')
                  setShowAllSpecies(false)
                }}
              >
                הכל · {detections.length}
              </button>
              {visibleCounts.map(([name, n]) => (
                <button
                  key={name}
                  className={`filter${species === name ? ' active' : ''}`}
                  onClick={() => setSpecies(species === name ? null : name)}
                >
                  {name} · {n}
                </button>
              ))}
            </div>
            {!query && sortedCounts.length > COMMON_SPECIES_LIMIT && (
              <button
                className="det-expand"
                aria-expanded={showAllSpecies}
                onClick={() => setShowAllSpecies((shown) => !shown)}
              >
                {showAllSpecies ? 'הצג נפוצים בלבד' : `הצג את כל הסוגים (${sortedCounts.length})`}
              </button>
            )}
          </div>
          <p className="muted small">גררו זיהויים לציר הזמן כדי להוסיף אותם.</p>
          {shown.length === 0 ? (
            <p className="muted small">לא נמצאו זיהויים התואמים לחיפוש.</p>
          ) : (
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
                    {d.source === 'manual' && <span className="soon">ידני</span>}
                    {d.corrected && <span className="soon">תוקן</span>}
                    <span className="muted small" dir="ltr">
                      {names.get(d.media_id) ?? ''}
                      {d.start_time != null &&
                        ` · ${formatDuration(d.start_time)}–${formatDuration(d.end_time)}`}
                      {d.source !== 'manual' && ` · ${Math.round(d.confidence * 100)}%`}
                    </span>
                  </button>
                  <button className="icon" aria-label="עריכת זיהוי" onClick={() => onEdit(d)}>
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
          )}
        </>
      )}
    </section>
  )
}
