import Icon from './icons'

export function Severity({ level }) {
  return <span className={`sev sev-${level.toLowerCase()}`}>{level}</span>
}

export function ConfidenceBar({ value }) {
  const percent = Math.round(value * 100)
  return (
    <div className="confidence" title={`${percent}%`}>
      <div className="confidence-track">
        <div className="confidence-fill" style={{ width: `${percent}%` }} />
      </div>
      <span>{percent}%</span>
    </div>
  )
}

export function Stat({ icon, label, value, sub }) {
  return (
    <div className="stat card">
      <span className="stat-label">{icon && <Icon name={icon} size={14} />}{label}</span>
      <span className="stat-value">{value}</span>
      {sub && <span className="stat-sub">{sub}</span>}
    </div>
  )
}

/** Status shown with icon + label, never color alone. */
export function Verdict({ correct }) {
  if (correct === null || correct === undefined) return null
  return correct
    ? <span className="pill good"><Icon name="check" />correct</span>
    : <span className="pill bad"><Icon name="x" />wrong</span>
}

export function Spinner() {
  return <span className="spinner" aria-hidden="true" />
}

/** Small ⓘ hint that explains a term on hover or keyboard focus. */
export function Info({ text }) {
  return (
    <span className="info" tabIndex={0} aria-label={text}>
      <Icon name="info" size={13} />
      <span className="info-pop" role="tooltip">{text}</span>
    </span>
  )
}
