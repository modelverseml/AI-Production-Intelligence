import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../api'
import BarList from '../components/BarList'
import Icon from '../components/icons'
import { Info, Severity, Spinner, Stat, Verdict } from '../components/ui'
import { formatDate } from '../format'

const STATUSES = [
  { value: 'ALL', label: 'Any status' },
  { value: 'open', label: 'Not analyzed yet' },
  { value: 'done', label: 'Analyzed' },
]
const PAGE_SIZE = 25
const GUIDE_KEY = 'incident_guide_hidden'

function guideHidden() {
  try {
    return localStorage.getItem(GUIDE_KEY) === '1'
  } catch {
    return false
  }
}

const STEPS = [
  { title: 'Pick an incident', text: 'Each one is a real outage from a benchmark: a single faulty service slowed or broke the system.' },
  { title: 'Run the AI analysis', text: 'An AI agent reads the metrics, logs and traces, asks an ML model for a second opinion, and names the faulty service.' },
  { title: 'Check the evidence', text: 'Every claim links to the data it came from, and you can reveal the true answer to see whether the agent was right.' },
]

function percent(value) {
  return value === null || value === undefined ? '—' : `${Math.round(value * 100)}%`
}

export default function Dashboard() {
  const navigate = useNavigate()
  const [incidents, setIncidents] = useState([])
  const [services, setServices] = useState({})
  const [stats, setStats] = useState(null)
  const [query, setQuery] = useState('')
  const [status, setStatus] = useState('ALL')
  const [page, setPage] = useState(0)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [showGuide, setShowGuide] = useState(() => !guideHidden())

  const hideGuide = () => {
    setShowGuide(false)
    try { localStorage.setItem(GUIDE_KEY, '1') } catch { /* storage unavailable */ }
  }

  useEffect(() => {
    Promise.all([api.incidents(), api.services(), api.stats()])
      .then(([incidentList, serviceList, statData]) => {
        setIncidents(incidentList)
        setServices(Object.fromEntries(serviceList.map((s) => [s.id, s.name])))
        setStats(statData)
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false))
  }, [])

  const filtered = useMemo(() => {
    const term = query.trim().toLowerCase()
    return incidents.filter((incident) => {
      if (status === 'open' && incident.investigations) return false
      if (status === 'done' && !incident.investigations) return false
      if (!term) return true
      return (
        incident.title.toLowerCase().includes(term) ||
        (services[incident.service_id] || '').includes(term) ||
        (incident.latest_prediction || '').toLowerCase().includes(term) ||
        String(incident.id) === term.replace('inc-', '')
      )
    })
  }, [incidents, services, query, status])

  const pageCount = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE))
  const current = Math.min(page, pageCount - 1)
  const rows = filtered.slice(current * PAGE_SIZE, (current + 1) * PAGE_SIZE)
  const agent = stats?.agent

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1>Incidents</h1>
          <p className="muted">Find which service caused each outage. Open an incident and let the AI agent investigate.</p>
        </div>
        {!showGuide && <button className="btn ghost" onClick={() => setShowGuide(true)}><Icon name="info" /> How it works</button>}
      </div>

      {showGuide && (
        <section className="card" style={{ marginBottom: 20 }}>
          <div className="card-header">
            <div className="card-title"><Icon name="sparkle" /><h2>How it works</h2></div>
            <button className="btn ghost dismiss" onClick={hideGuide} aria-label="Hide guide"><Icon name="x" /></button>
          </div>
          <div className="steps">
            {STEPS.map((step, i) => (
              <div key={step.title} className="step">
                <span className="step-num">{i + 1}</span>
                <div><strong>{step.title}</strong><p>{step.text}</p></div>
              </div>
            ))}
          </div>
        </section>
      )}

      {error && <div className="alert error">{error}</div>}

      <div className="stats">
        <Stat icon="alert" label="Incidents" value={stats?.incidents.total ?? '—'}
          sub={stats ? `${stats.incidents.by_system.length} applications · RCAEval benchmark` : ' '} />
        <Stat icon="sparkle" label="Analyses run" value={stats?.investigations.total ?? '—'}
          sub={stats ? Object.entries(stats.investigations.by_method).map(([m, n]) => `${n} ${m}`).join(' · ') || 'none yet' : ' '} />
        <Stat icon="check" label={<>Agent got it right <Info text="Share of analyses run in this app where the agent's #1 pick was the true faulty service." /></>}
          value={percent(agent?.accuracy)}
          sub={agent ? `in ${agent.runs} analyses (${agent.from_evaluation} from the benchmark evaluation)` : 'run the agent on an incident'} />
        <Stat icon="shield" label={<>Evidence verified <Info text="Share of reports where every piece of evidence the agent cited was actually returned by its tools, so nothing was made up." /></>}
          value={percent(agent?.grounded_rate)}
          sub={agent ? `about ${agent.avg_tool_calls} data lookups per analysis` : 'no made-up citations'} />
      </div>

      <div className="dash-grid">
        <div className="card">
          <div className="card-header">
            <div className="card-title"><Icon name="layers" /><h2>Incidents by system</h2></div>
          </div>
          {stats && (
            <BarList
              rows={stats.incidents.by_system.map((s) => ({ label: s.system, value: s.count }))}
              tooltip={(row) => <><strong>{row.label}</strong>{row.value} incidents</>}
            />
          )}
        </div>
        <div className="card">
          <div className="card-header">
            <div className="card-title"><Icon name="clock" /><h2>Typical AI analysis</h2></div>
          </div>
          {agent ? (
            <dl className="metrics two" style={{ marginBottom: 0 }}>
              <div><dt>time taken</dt><dd>{agent.avg_latency_s}s</dd></div>
              <div><dt>data lookups</dt><dd>{agent.avg_tool_calls}</dd></div>
              <div><dt>cost (estimate)</dt><dd>${agent.avg_cost_usd.toFixed(3)}</dd></div>
              <div><dt>analyses</dt><dd>{agent.runs}</dd></div>
            </dl>
          ) : (
            <p className="muted">No agent runs yet. Open a benchmark incident and select <strong>Run root-cause analysis</strong>.</p>
          )}
          <Link to="/benchmarks" className="link" style={{ marginTop: 14 }}>How accurate is it overall? <Icon name="chart" size={14} /></Link>
        </div>
      </div>

      <div className="toolbar">
        <div className="search">
          <Icon name="search" />
          <input
            placeholder="Search title, service, prediction or INC-id"
            value={query}
            onChange={(e) => { setQuery(e.target.value); setPage(0) }}
            aria-label="Search incidents"
          />
        </div>
        <select value={status} onChange={(e) => { setStatus(e.target.value); setPage(0) }} aria-label="Filter by status">
          {STATUSES.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
        </select>
      </div>

      <div className="card table-card">
        <table>
          <thead>
            <tr>
              <th>Incident</th>
              <th>System <Info text="The application that failed, and the front-door service where users noticed it." /></th>
              <th>Severity</th>
              <th>AI finding <Info text="The service the agent blamed in its latest analysis, and whether that matches the benchmark's true answer." /></th>
              <th>Opened</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((incident) => (
              <tr key={incident.id} className="clickable" onClick={() => navigate(`/incidents/${incident.id}`)}>
                <td>
                  <Link to={`/incidents/${incident.id}`} className="row-title" onClick={(e) => e.stopPropagation()}>{incident.title}</Link>
                  <div className="muted small mono">INC-{incident.id}</div>
                </td>
                <td>
                  <div className="small">{incident.system}</div>
                  <span className="muted small mono">{services[incident.service_id]}</span>
                </td>
                <td><Severity level={incident.severity} /></td>
                <td>
                  {incident.latest_prediction ? (
                    <div className="status-cell">
                      <span className="mono small strong">{incident.latest_prediction}</span>
                      <Verdict correct={incident.latest_correct} />
                    </div>
                  ) : (
                    <span className="pill neutral">Not analyzed yet</span>
                  )}
                </td>
                <td className="muted small">{formatDate(incident.created_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {!loading && filtered.length === 0 && <div className="empty">No incidents match these filters.</div>}
        {loading && <div className="page-loading"><Spinner /> Loading incidents…</div>}
        {filtered.length > PAGE_SIZE && (
          <div className="pager">
            <span>{current * PAGE_SIZE + 1}–{Math.min(filtered.length, (current + 1) * PAGE_SIZE)} of {filtered.length}</span>
            <div style={{ display: 'flex', gap: 6 }}>
              <button className="btn" disabled={current === 0} onClick={() => setPage(current - 1)}>Previous</button>
              <button className="btn" disabled={current >= pageCount - 1} onClick={() => setPage(current + 1)}>Next</button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
