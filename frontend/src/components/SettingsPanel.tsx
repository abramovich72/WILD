import { useState } from 'react'
import type { MusicStyle, Transition } from '../api'

const STYLES: { value: MusicStyle; label: string }[] = [
  { value: 'electronic', label: 'אלקטרוני' },
  { value: 'acoustic', label: 'אקוסטי' },
  { value: 'ambient', label: 'אווירה' },
]

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
  musicEnabled: boolean
  onMusicEnabled: (enabled: boolean) => void
  musicPrompt: string
  onMusicPrompt: (prompt: string) => void
  musicStyle: MusicStyle
  onMusicStyle: (style: MusicStyle) => void
  musicVolume: number
  onMusicVolume: (volume: number) => void
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
  musicEnabled,
  onMusicEnabled,
  musicPrompt,
  onMusicPrompt,
  musicStyle,
  onMusicStyle,
  musicVolume,
  onMusicVolume,
}: Props) {
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

      <section>
        <label className="row">
          <input
            type="checkbox"
            checked={musicEnabled}
            onChange={(event) => onMusicEnabled(event.target.checked)}
          />
          <h3>הוסף מוזיקה</h3>
        </label>
        {musicEnabled && (
          <div className="music-fields">
            <label className="small muted" htmlFor="music-prompt">תיאור המוזיקה</label>
            <textarea
              id="music-prompt"
              rows={4}
              maxLength={500}
              value={musicPrompt}
              onChange={(event) => onMusicPrompt(event.target.value)}
              placeholder="למשל: calm instrumental music for a nature documentary"
            />
            <span className="muted small">תיאור באנגלית בדרך כלל מניב תוצאות טובות יותר.</span>
            <label className="small muted">סגנון</label>
            <div className="style-options">
              {STYLES.map((option) => (
                <button
                  key={option.value}
                  type="button"
                  className={`style${option.value === musicStyle ? ' active' : ''}`}
                  aria-pressed={option.value === musicStyle}
                  onClick={() => onMusicStyle(option.value)}
                >
                  {option.label}
                </button>
              ))}
            </div>
            <div className="row between">
              <span className="small muted">עוצמת המוזיקה</span>
              <strong>{musicVolume}%</strong>
            </div>
            <input
              type="range"
              min={0}
              max={200}
              value={musicVolume}
              aria-label="עוצמת המוזיקה"
              onChange={(event) => onMusicVolume(+event.target.value)}
            />
            <p className="music-notice muted small" role="note">
              יצירת המוזיקה מתבצעת ברקע ועשויה להימשך כשתי דקות ל־30 שניות מוזיקה. ביצירה הראשונה
              הורדת המודל עשויה להאריך את ההמתנה.
            </p>
          </div>
        )}
      </section>

      <div className="settings-footer muted small">MP4 · 720p · 30fps</div>
    </aside>
  )
}
