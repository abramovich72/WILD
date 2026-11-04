import { useState } from 'react'
import type { Transition } from '../api'

const STYLES = ['אלקטרוני', 'אקוסטי', 'אווירה']

type Props = {
  length: number
  onLength: (seconds: number) => void
  captions: boolean
  onCaptions: (on: boolean) => void
  openingTitle: string
  onOpeningTitle: (text: string) => void
  openingTitleSeconds: number
  onOpeningTitleSeconds: (seconds: number) => void
  closingTitle: string
  onClosingTitle: (text: string) => void
  closingTitleSeconds: number
  onClosingTitleSeconds: (seconds: number) => void
  transition: Transition
  onTransition: (t: Transition) => void
}

export function SettingsPanel({
  length,
  onLength,
  captions,
  onCaptions,
  openingTitle,
  onOpeningTitle,
  openingTitleSeconds,
  onOpeningTitleSeconds,
  closingTitle,
  onClosingTitle,
  closingTitleSeconds,
  onClosingTitleSeconds,
  transition,
  onTransition,
}: Props) {
  const [style, setStyle] = useState(STYLES[0])
  const [volume, setVolume] = useState(110)
  const [titlesCollapsed, setTitlesCollapsed] = useState(
    () => localStorage.getItem('titles-collapsed') !== '0',
  )

  function toggleTitles() {
    setTitlesCollapsed((collapsed) => {
      const next = !collapsed
      localStorage.setItem('titles-collapsed', next ? '1' : '0')
      return next
    })
  }

  return (
    <aside className="panel settings">
      <section>
        <h3>אורך הסרטון</h3>
        <div className="big-number">{length}</div>
        <span className="muted small center">שניות</span>
        <input
          type="range"
          min={5}
          max={180}
          value={length}
          onChange={(e) => onLength(+e.target.value)}
        />
        <div className="range-labels">
          <span>5 שנ׳</span>
          <span>3 דק׳</span>
        </div>
      </section>

      <section>
        <label className="row">
          <input type="checkbox" checked={captions} onChange={(e) => onCaptions(e.target.checked)} />
          <h3>כיתובי שמות בעלי החיים</h3>
        </label>
        <span className="muted small">שם המין בתחתית כל קטע</span>
      </section>

      <section>
        <button
          type="button"
          className="row between collapse-head"
          aria-expanded={!titlesCollapsed}
          aria-controls="title-fields"
          onClick={toggleTitles}
        >
          <h3>כותרות פתיחה וסיום</h3>
          <span className="chevron">{titlesCollapsed ? '◀' : '▼'}</span>
        </button>
        {!titlesCollapsed && (
          <div id="title-fields" className="title-fields">
            <span className="muted small">כותרת פתיחה תופיע לפני הקטעים; כותרת סיום אחריהם.</span>
            <label className="small muted" htmlFor="opening-title">כותרת פתיחה</label>
            <input
              id="opening-title"
              className="title-text"
              maxLength={200}
              value={openingTitle}
              onChange={(e) => onOpeningTitle(e.target.value)}
              placeholder="למשל: חיות הבר בישראל"
            />
            <label className="small muted" htmlFor="opening-title-seconds">משך בשניות</label>
            <input
              id="opening-title-seconds"
              className="title-seconds"
              type="number"
              min={1}
              max={60}
              step={0.5}
              value={openingTitleSeconds}
              onChange={(e) =>
                onOpeningTitleSeconds(Math.min(60, Math.max(1, Number(e.target.value) || 1)))
              }
            />

            <label className="small muted" htmlFor="closing-title">כותרת סיום</label>
            <input
              id="closing-title"
              className="title-text"
              maxLength={200}
              value={closingTitle}
              onChange={(e) => onClosingTitle(e.target.value)}
              placeholder="למשל: תודה שצפיתם"
            />
            <label className="small muted" htmlFor="closing-title-seconds">משך בשניות</label>
            <input
              id="closing-title-seconds"
              className="title-seconds"
              type="number"
              min={1}
              max={60}
              step={0.5}
              value={closingTitleSeconds}
              onChange={(e) =>
                onClosingTitleSeconds(Math.min(60, Math.max(1, Number(e.target.value) || 1)))
              }
            />
          </div>
        )}
      </section>

      <section>
        <label className="small muted">מעבר בין קטעים</label>
        <select value={transition} onChange={(e) => onTransition(e.target.value as Transition)}>
          <option value="none">ללא</option>
          <option value="fade">דהייה לשחור</option>
        </select>
      </section>

      <section className="disabled" title="יופעל בשלב 4">
        <h3>המוזיקה שלך</h3>
        <label className="small muted">תיאור המוזיקה</label>
        <textarea
          disabled
          rows={4}
          defaultValue="אלקטרוניקה קצבית, אווירה מסתורית, ללא שירה"
        />
        <label className="small muted">סגנון</label>
        <div className="style-options">
          {STYLES.map((s) => (
            <button key={s} className={`style${s === style ? ' active' : ''}`} onClick={() => setStyle(s)}>
              {s}
            </button>
          ))}
        </div>
        <div className="row between">
          <span className="small muted">עוצמה</span>
          <strong>{volume}%</strong>
        </div>
        <input
          type="range"
          min={0}
          max={200}
          value={volume}
          onChange={(e) => setVolume(+e.target.value)}
        />
        <div className="options small">
          <div>גלם</div>
          <label><input type="checkbox" defaultChecked disabled /> מוזיקה</label>
          <label><input type="checkbox" defaultChecked disabled /> אנימציה</label>
          <div>אפקטים</div>
          <label><input type="checkbox" disabled /> התאמת קצב</label>
          <label><input type="checkbox" disabled /> Fade</label>
        </div>
      </section>

      <div className="settings-footer muted small">MP4 · 720p · 30fps</div>
    </aside>
  )
}
