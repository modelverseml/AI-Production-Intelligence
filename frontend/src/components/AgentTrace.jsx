import Icon from './icons'

const TOOL_ICONS = {
  get_ml_ranking: 'sparkle',
  get_top_anomalies: 'activity',
  get_service_metrics: 'cpu',
  get_service_logs: 'file',
  get_service_traces: 'route',
  get_dependencies: 'graph',
  search_runbooks: 'book',
  list_services: 'layers',
  submit_report: 'check',
}

function describe(step) {
  const a = step.arguments || {}
  switch (step.tool) {
    case 'get_ml_ranking': return 'Asked the ML model which services are most likely at fault'
    case 'get_top_anomalies': return `Looked for the ${a.limit || ''} metrics that changed most after the alert`
    case 'get_service_metrics': return `Checked the metrics (CPU, memory, latency…) of ${a.service}`
    case 'get_service_logs': return `Read the logs of ${a.service}, looking for new errors`
    case 'get_service_traces': return `Checked request traces to ${a.service} for errors and slowdowns`
    case 'get_dependencies': return `Looked up which services ${a.service} calls and is called by`
    case 'search_runbooks': return `Searched the runbooks for “${a.query}”`
    case 'list_services': return 'Listed all services in the system'
    case 'submit_report': return step.ok ? 'Submitted the final report, and the evidence check passed' : 'Submitted a report, but the evidence check rejected it'
    default: return step.tool
  }
}

export default function AgentTrace({ trace }) {
  return (
    <ol className="timeline">
      {trace.map((step, index) => {
        const kind = step.tool === 'get_ml_ranking' ? 'ml'
          : step.tool === 'submit_report' ? (step.ok ? 'submit' : 'failed')
          : step.ok ? '' : 'failed'
        return (
          <li key={index} className={kind}>
            <span className="dot"><Icon name={step.ok ? (TOOL_ICONS[step.tool] || 'tool') : 'x'} size={15} /></span>
            <div>
              <div className="step-text">{describe(step)}</div>
              <div className="step-args">{step.tool}</div>
              {step.problems?.length > 0 && <div className="small" style={{ color: 'var(--critical-ink)' }}>Rejected: {step.problems.join('; ')}</div>}
            </div>
            <span className="step-meta">
              step {index + 1}
            </span>
          </li>
        )
      })}
    </ol>
  )
}
