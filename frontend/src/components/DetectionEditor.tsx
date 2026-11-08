import { useEffect, useState } from 'react'
import { api, type Detection, type MediaItem, type SpeciesOption } from '../api'

const CUSTOM_SPECIES = '__custom__'

type Props = {
  item: MediaItem
  detection: Detection | null
  initialTime: number
  onClose: () => void
  onSaved: () => void
}

function initialStart(item: MediaItem, detection: Detection | null, time: number) {
  if (detection?.start_time != null) return detection.start_time
  const maximum = item.duration == null ? Math.max(time, 0) : Math.max(0, item.duration - 0.2)
  return Math.min(Math.max(time, 0), maximum)
}

export function DetectionEditor({ item, detection, initialTime, onClose, onSaved }: Props) {
  const start = initialStart(item, detection, initialTime)
  const initialEnd =
    detection?.end_time ??
    Math.min(start + 1, item.duration ?? start + 1)
  const [options, setOptions] = useState<SpeciesOption[]>([])
  const [choice, setChoice] = useState(CUSTOM_SPECIES)
  const [customSpecies, setCustomSpecies] = useState(detection?.species ?? '')
  const [startTime, setStartTime] = useState(String(start))
  const [endTime, setEndTime] = useState(String(initialEnd))
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    let active = true
    api
      .species()
      .then((species) => {
        if (!active) return
        setOptions(species)
        if (detection && species.some((option) => option.species === detection.species)) {
          setChoice(detection.species)
          setCustomSpecies('')
        } else if (!detection && species.some((option) => option.species === 'unknown animal')) {
          setChoice('unknown animal')
          setCustomSpecies('')
        } else if (detection) {
          setChoice(CUSTOM_SPECIES)
          setCustomSpecies(detection.species)
        }
      })
      .catch(() => {
        if (active) setError('לא ניתן לטעון את רשימת המינים')
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    return () => {
      active = false
    }
  }, [detection])

  async function save(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const species = (choice === CUSTOM_SPECIES ? customSpecies : choice).trim()
    if (!species) {
      setError('יש לבחור מין או להזין שם')
      return
    }
    let start: number | null = null
    let end: number | null = null
    if (item.kind === 'video') {
      start = Number(startTime)
      end = Number(endTime)
      if (!Number.isFinite(start) || !Number.isFinite(end) || start < 0 || end <= start) {
        setError('יש להזין טווח זמנים תקין')
        return
      }
      if (item.duration != null && end > item.duration) {
        setError('טווח הזמנים חורג מאורך הסרטון')
        return
      }
    }
    setSaving(true)
    setError('')
    try {
      if (detection) {
        await api.updateDetection(detection.id, { species, start_time: start, end_time: end })
      } else {
        await api.createDetection(item.id, { species, start_time: start, end_time: end })
      }
      onSaved()
    } catch (e) {
      setError(`שמירת הזיהוי נכשלה${e instanceof Error ? `: ${e.message}` : ''}`)
      setSaving(false)
    }
  }

  return (
    <div
      className="modal-back"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose()
      }}
    >
      <div
        className="modal detection-editor"
        role="dialog"
        aria-modal="true"
        aria-labelledby="detection-editor-title"
        onKeyDown={(event) => event.key === 'Escape' && onClose()}
      >
        <div className="row between">
          <h2 id="detection-editor-title">{detection ? 'עריכת זיהוי' : 'הוספת זיהוי'}</h2>
          <button type="button" className="icon" aria-label="סגירה" onClick={onClose}>
            ✕
          </button>
        </div>
        <p className="muted small">{item.filename}</p>
        <form className="detection-form" onSubmit={(event) => void save(event)}>
          <label>
            מין
            <select
              value={choice}
              disabled={loading}
              onChange={(event) => setChoice(event.target.value)}
            >
              {options.map((option) => (
                <option key={option.species} value={option.species}>
                  {option.display}
                </option>
              ))}
              <option value={CUSTOM_SPECIES}>מין אחר…</option>
            </select>
          </label>
          {choice === CUSTOM_SPECIES && (
            <label>
              שם המין
              <input
                autoFocus
                maxLength={120}
                value={customSpecies}
                onChange={(event) => setCustomSpecies(event.target.value)}
                placeholder="לדוגמה: גירית מצויה"
              />
            </label>
          )}
          {item.kind === 'video' && (
            <div className="detection-time-fields">
              <label>
                התחלה (שניות)
                <input
                  type="number"
                  min="0"
                  step="0.1"
                  value={startTime}
                  onChange={(event) => setStartTime(event.target.value)}
                />
              </label>
              <label>
                סיום (שניות)
                <input
                  type="number"
                  min="0"
                  step="0.1"
                  value={endTime}
                  onChange={(event) => setEndTime(event.target.value)}
                />
              </label>
            </div>
          )}
          {error && <p className="error small" role="alert">{error}</p>}
          <div className="row">
            <button type="submit" className="primary" disabled={loading || saving}>
              {saving ? 'שומר…' : 'שמירה'}
            </button>
            <button type="button" className="filter" onClick={onClose}>
              ביטול
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
