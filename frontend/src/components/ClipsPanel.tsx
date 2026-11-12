import { api, type Clip } from '../api'
import { formatDuration, formatSize } from '../format'

const STATUS: Record<Clip['status'], string> = {
  queued: 'בתור',
  running: 'מרנדר',
  done: 'מוכן',
  failed: 'נכשל',
}

export function ClipsPanel({ clips, onChanged }: { clips: Clip[]; onChanged: () => void }) {
  return (
    <section className="panel">
      <div className="row between">
        <h2>התוצרים שלי</h2>
        <span className="muted small">{clips.length} קליפים</span>
      </div>
      {clips.length === 0 ? (
        <p className="muted small">אין תוצרים עדיין. עברו לעריכה והפיקו סרטון.</p>
      ) : (
        <div className="clip-list">
          {clips.map((c) => (
            <article key={c.id} className="clip-card">
              {c.status === 'done' ? (
                <video className="clip-player" src={api.clipUrl(c.id)} controls preload="metadata" />
              ) : (
                <div className="clip-placeholder">
                  {c.status === 'failed' ? 'יצירת הסרטון נכשלה' : STATUS[c.status]}
                </div>
              )}
              <div className="clip-card-info">
                <div className="row between">
                  <strong>{c.name}</strong>
                  <span className={`clip-status ${c.status}`}>{STATUS[c.status]}</span>
                </div>
                <div className="clip-metadata muted small">
                  {c.status === 'done' && (
                    <span>{formatDuration(c.duration)} · MP4 · 720p · 30 FPS · {formatSize(c.size_bytes)}</span>
                  )}
                  {c.status === 'failed' && c.error && <span>{c.error}</span>}
                </div>
                {c.status === 'running' || c.status === 'queued' ? (
                  <>
                    <div className="bar">
                      <i style={{ width: `${Math.round((c.progress ?? 0) * 100)}%` }} />
                    </div>
                    {c.spec.music?.enabled && c.spec.music.volume > 0 && (
                      <p className="music-notice muted small">
                        יצירת המוזיקה מתבצעת ברקע ועשויה להימשך כמה דקות.
                      </p>
                    )}
                  </>
                ) : null}
                <div className="row between clip-actions">
                  {c.status === 'done' ? (
                    <a className="filter" href={api.clipUrl(c.id, true)}>
                      הורדת הסרטון <span aria-hidden="true">⬇</span>
                    </a>
                  ) : <span />}
                  <button
                    className="icon danger"
                    aria-label={`מחיקת ${c.name}`}
                    disabled={c.status === 'queued' || c.status === 'running'}
                    onClick={async () => {
                      if (!confirm(`למחוק את ${c.name}?`)) return
                      await api.deleteClip(c.id)
                      onChanged()
                    }}
                  >
                    ✕
                  </button>
                </div>
              </div>
            </article>
          ))}
        </div>
      )}
    </section>
  )
}
