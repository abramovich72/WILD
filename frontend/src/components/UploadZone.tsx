import { useRef, useState } from 'react'
import { type MediaItem, uploadFile } from '../api'

type Job = { name: string; progress: number; error?: string }

type Props = {
  projectId: number
  onUploaded: (item: MediaItem) => void
}

export function UploadZone({ projectId, onUploaded }: Props) {
  const input = useRef<HTMLInputElement>(null)
  const [jobs, setJobs] = useState<Record<string, Job>>({})
  const [dragging, setDragging] = useState(false)

  const patch = (key: string, job: Partial<Job>) =>
    setJobs((j) => ({ ...j, [key]: { ...j[key], ...job } }))

  async function handle(files: FileList | File[]) {
    for (const file of Array.from(files)) {
      const key = `${file.name}-${file.size}-${Math.random()}`
      patch(key, { name: file.name, progress: 0 })
      try {
        const item = await uploadFile(projectId, file, (p) => patch(key, { progress: p }))
        onUploaded(item)
        setJobs((j) => Object.fromEntries(Object.entries(j).filter(([k]) => k !== key)))
      } catch {
        patch(key, { error: 'ההעלאה נכשלה' })
      }
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
        <span>או לחיצה לבחירת קבצים מהמחשב</span>
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
