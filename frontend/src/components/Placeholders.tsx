function Locked({ title, stage, children }: { title: string; stage: number; children?: React.ReactNode }) {
  return (
    <section className="panel locked" title={`יופעל בשלב ${stage}`}>
      <div className="row between">
        <h3>{title}</h3>
        <span className="soon">בקרוב</span>
      </div>
      {children}
    </section>
  )
}

export function SoundtrackPanel() {
  return (
    <Locked title="פס קול" stage={4}>
      <div className="waveform" />
    </Locked>
  )
}
