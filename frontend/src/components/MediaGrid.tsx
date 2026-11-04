import { useMemo, useState } from 'react'
import { api, type MediaItem } from '../api'
import { formatDuration } from '../format'

type Props = {
  items: MediaItem[]
  species: Map<number, string>
  selectedId: number | null
  checked: Set<number>
  onSelect: (id: number) => void
  onToggleChecked: (id: number) => void
  onSetChecked: (ids: number[]) => void
  onDeleted: (id: number) => void
}

type Filter = 'all' | 'video' | 'image'
type Sort = 'new' | 'name'

const FILTERS: [Filter, string][] = [
  ['all', 'הכל'],
  ['video', 'סרטונים'],
  ['image', 'תמונות'],
]

export function MediaGrid({
  items,
  species,
  selectedId,
  checked,
  onSelect,
  onToggleChecked,
  onSetChecked,
  onDeleted,
}: Props) {
  const [filter, setFilter] = useState<Filter>('all')
  const [sort, setSort] = useState<Sort>('new')
  const [deleting, setDeleting] = useState(false)
  const [deleteError, setDeleteError] = useState('')

  const shown = useMemo(() => {
    const list = items.filter((m) => filter === 'all' || m.kind === filter)
    return sort === 'name'
      ? [...list].sort((a, b) => a.filename.localeCompare(b.filename))
      : [...list].sort((a, b) => b.id - a.id)
  }, [items, filter, sort])
  const allChecked = items.length > 0 && items.every((m) => checked.has(m.id))

  async function deleteSelected() {
    const ids = [...checked]
    if (!ids.length || deleting) return
    if (!confirm(`למחוק ${ids.length} קבצים? הקבצים יימחקו גם מהדיסק.`)) return

    setDeleting(true)
    setDeleteError('')
    let failed = 0
    for (const id of ids) {
      try {
        await api.deleteMedia(id)
        onDeleted(id)
      } catch {
        failed += 1
      }
    }
    if (failed) setDeleteError(`מחיקת ${failed} קבצים נכשלה. הם נשארו בספרייה.`)
    setDeleting(false)
  }

  return (
    <div className="library">
      <div className="filters">
        {FILTERS.map(([key, label]) => (
          <button
            key={key}
            className={`filter${filter === key ? ' active' : ''}`}
            onClick={() => setFilter(key)}
          >
            {label}
          </button>
        ))}
        <select value={sort} onChange={(e) => setSort(e.target.value as Sort)} aria-label="מיון">
          <option value="new">החדשים</option>
          <option value="name">לפי שם</option>
        </select>
      </div>
      <label className="media-select-all">
        <input
          type="checkbox"
          checked={allChecked}
          disabled={items.length === 0 || deleting}
          onChange={() =>
            onSetChecked(allChecked ? [] : items.map((item) => item.id))
          }
        />
        בחר את כל הקבצים ({items.length})
      </label>
      <div className="grid">
        {shown.map((m) => (
          <div
            key={m.id}
            className={`card${m.id === selectedId ? ' selected' : ''}`}
            onClick={() => onSelect(m.id)}
            draggable
            onDragStart={(e) => {
              e.dataTransfer.effectAllowed = 'copy'
              e.dataTransfer.setData(
                'application/x-wild-detection',
                JSON.stringify({
                  media_id: m.id,
                  start: null,
                  end: null,
                  label: species.get(m.id) ?? null,
                }),
              )
            }}
          >
            <div className="thumb">
              {m.thumb_name ? (
                <img src={api.thumbUrl(m.id)} alt={m.filename} loading="lazy" draggable={false} />
              ) : (
                <div className="nothumb" />
              )}
              {m.kind === 'video' && (
                <span className="badge">▶ {formatDuration(m.duration)}</span>
              )}
              {m.detect_status === 'failed' ? (
                <span className="tag warn" title={m.detect_error ?? ''}>
                  הזיהוי נכשל
                </span>
              ) : m.detect_status === 'queued' || m.detect_status === 'running' ? (
                <span className="tag wait">מזהה…</span>
              ) : (
                species.has(m.id) ? (
                  <span className="tag">{species.get(m.id)}</span>
                ) : (
                  m.detect_status === 'done' && <span className="tag">לא זוהה</span>
                )
              )}
              <button
                className={`check${checked.has(m.id) ? ' on' : ''}`}
                aria-label="סימון למחיקה"
                onClick={(e) => {
                  e.stopPropagation()
                  onToggleChecked(m.id)
                }}
              >
                ✓
              </button>
              <button
                className="del"
                aria-label="מחיקה"
                onClick={async (e) => {
                  e.stopPropagation()
                  if (!confirm(`למחוק את ${m.filename}?`)) return
                  await api.deleteMedia(m.id)
                  onDeleted(m.id)
                }}
              >
                ✕
              </button>
            </div>
            <div className="name" title={m.filename}>
              {m.filename}
            </div>
          </div>
        ))}
      </div>
      {shown.length === 0 && <p className="muted center-text">אין מדיה להצגה</p>}
      <div className="library-footer">
        {checked.size} נבחרו · {items.length} קבצים
        {checked.size > 0 && (
          <button className="filter" disabled={deleting} onClick={() => void deleteSelected()}>
            {deleting ? 'מוחק…' : `מחק נבחרים (${checked.size})`}
          </button>
        )}
      </div>
      {deleteError && <p className="error small">{deleteError}</p>}
    </div>
  )
}
