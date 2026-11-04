import { useEffect, useRef, useState } from 'react'
import { api, type Detection, type MediaItem } from '../api'
import { formatDuration, formatSize } from '../format'

type Props = { item: MediaItem | null; detections: Detection[]; seek: { time: number; n: number } | null }

export function Preview({ item, detections, seek }: Props) {
  const video = useRef<HTMLVideoElement>(null)
  const [now, setNow] = useState(0)

  useEffect(() => {
    if (seek && video.current) {
      video.current.currentTime = seek.time
      void video.current.play().catch(() => {})
    }
  }, [seek])

  if (!item) return <div className="preview empty">בחרו פריט לתצוגה מקדימה</div>
  const src = item.kind === 'video' ? api.previewUrl(item.id) : api.fileUrl(item.id)
  const mine = detections.filter((d) => d.media_id === item.id)
  const active = mine.filter(
    (d) => d.start_time != null && now >= d.start_time && now <= (d.end_time ?? d.start_time),
  )

  return (
    <div className="preview">
      <div className={`stage ${item.kind}`}>
        {item.kind === 'video' ? (
          <video
            ref={video}
            key={item.id}
            src={src}
            controls
            preload="metadata"
            onTimeUpdate={(e) => setNow(e.currentTarget.currentTime)}
            onLoadedMetadata={(e) => {
              if (seek) e.currentTarget.currentTime = seek.time
            }}
          />
        ) : (
          <img key={item.id} src={src} alt={item.filename} />
        )}
        {item.kind === 'image' &&
          mine.map(
            (d) =>
              d.box_x != null && (
                <div
                  key={d.id}
                  className="box"
                  style={{
                    left: `${d.box_x * 100}%`,
                    top: `${(d.box_y ?? 0) * 100}%`,
                    width: `${(d.box_w ?? 0) * 100}%`,
                    height: `${(d.box_h ?? 0) * 100}%`,
                  }}
                >
                  <span className="box-label">{d.display}</span>
                </div>
              ),
          )}
        {item.kind === 'video' && active.length > 0 && (
          <div className="video-tags">
            {active.map((d) => (
              <span key={d.id} className="box-label">
                {d.display}
              </span>
            ))}
          </div>
        )}
      </div>
      <div className="meta">
        <strong>{item.filename}</strong>
        <span dir="ltr">
          {[
            item.width && item.height ? `${item.width}×${item.height}` : '',
            item.kind === 'video' ? formatDuration(item.duration) : '',
            formatSize(item.size_bytes),
          ]
            .filter(Boolean)
            .join(' · ')}
        </span>
      </div>
    </div>
  )
}
