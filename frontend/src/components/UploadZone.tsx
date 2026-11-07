import { useRef, useState } from 'react'
import { MAX_UPLOAD_BYTES, type MediaItem, uploadFile } from '../api'

type Job = { name: string; progress: number; error?: string }

type Props = {
  projectId: number
  onUploaded: (item: MediaItem) => void
}

export function UploadZone({ projectId, onUploaded }: Props) {
  const input = useRef<HTMLInputElement>(null)
  const uploadSummaryRef = useRef({ total: 0, uploaded: 0, active: 0 })
  const [jobs, setJobs] = useState<Record<string, Job>>({})
  const [uploadSummary, setUploadSummary] = useState<{ total: number; uploaded: number } | null>(
    null,
  )
  const [dragging, setDragging] = useState(false)

  const patch = (key: string, job: Partial<Job>) =>
    setJobs((j) => ({ ...j, [key]: { ...j[key], ...job } }))

  async function handle(files: FileList | File[]) {
    const selectedFiles = Array.from(files)
    if (!selectedFiles.length) return

    const summary = uploadSummaryRef.current
    if (summary.active === 0) {
      summary.total = 0
      summary.uploaded = 0
    }
    summary.total += selectedFiles.length
    summary.active += 1
    const updateSummary = () =>
      setUploadSummary({ total: summary.total, uploaded: summary.uploaded })
    updateSummary()

    try {
      for (const file of selectedFiles) {
        const key = `${file.name}-${file.size}-${Math.random()}`
        patch(key, { name: file.name, progress: 0 })
        if (file.size > MAX_UPLOAD_BYTES) {
          patch(key, { error: 'הקובץ חורג מהמגבלה של 50 MB' })
          continue
        }
        try {
          const item = await uploadFile(projectId, file, (p) => patch(key, { progress: p }))
          onUploaded(item)
          summary.uploaded += 1
          updateSummary()
          setJobs((j) => Object.fromEntries(Object.entries(j).filter(([k]) => k !== key)))
        } catch {
          patch(key, { error: 'ההעלאה נכשלה' })
        }
      }
    } finally {
      summary.active -= 1
    }
  }

  return (
    <div>
      <div
        className={`dropzone${dragging ? ' dragging' : ''}`}
        onClick={() => input.current?.click()}
        onDragOver={(e) => {
          e.preventDefault()
          setDragging(true)
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault()
          setDragging(false)
          void handle(Array.from(e.dataTransfer.files))
        }}
      >
        <strong>גרירת תמונות וסרטונים</strong>
        <span>או לחיצה לבחירת קבצים מהמחשב (עד 50 MB לקובץ)</span>
        <input
          ref={input}
          type="file"
          multiple
          hidden
          accept="video/*,image/*"
          onChange={(e) => {
            if (e.target.files) void handle(Array.from(e.target.files))
            e.target.value = ''
          }}
        />
      </div>
      {uploadSummary && (
        <p className="upload-summary muted small" role="status" aria-live="polite">
          הועלו {uploadSummary.uploaded} מתוך {uploadSummary.total} קבצים
        </p>
      )}
      {Object.entries(jobs).map(([key, job]) => (
        <div key={key} className="job">
          <span>{job.name}</span>
          {job.error ? (
            <span className="error">{job.error}</span>
          ) : (
            <progress value={job.progress} max={1} />
          )}
        </div>
      ))}
    </div>
  )
}
