import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api'
import { useAuth } from '../auth'
import AgentReport from '../components/AgentReport'
import AgentTrace from '../components/AgentTrace'
import BarList from '../components/BarList'
import Icon from '../components/icons'
import ServiceGraph from '../components/ServiceGraph'
import { Info, Severity, Spinner, Verdict } from '../components/ui'
import { formatDate } from '../format'

const MODES = [
  { value: 'hybrid', label: 'AI + ML model', hint: 'The agent starts from an ML model trained on past incidents and checks it against the data. Usually the most accurate.' },
  { value: 'agent', label: 'AI only', hint: 'The agent investigates on its own, without the ML model.' },
]

export default function Incident() {
  const { id } = useParams()
  const { hasRole } = useAuth()
  const [incident, setIncident] = useState(null)
  const [service, setService] = useState(null)
  const [telemetry, setTelemetry] = useState(null)
  const [investigations, setInvestigations] = useState([])
  const [selected, setSelected] = useState(0)
  const [tab, setTab] = useState('analysis')
  const [running, setRunning] = useState(false)
  const [mode, setMode] = useState('hybrid')
  const [showLabel, setShowLabel] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    Promise.all([api.incident(id), api.investigations(id), api.services(), api.telemetry(id)])
      .then(([incidentData, history, services, telemetryData]) => {
        setIncident(incidentData)
        setInvestigations(history)
        setService(services.find((s) => s.id === incidentData.service_id) || null)
        setTelemetry(telemetryData)
      })
      .catch((err) => setError(err.message))
  }, [id])

  if (error && !incident) return <div className="page"><div className="alert error">{error}</div></div>
  if (!incident) return <div className="page-loading"><Spinner /> Loading incident…</div>

  const current = investigations[selected]
  const canInvestigate = hasRole('analyst', 'admin')
  const truth = incident.root_cause.split(' (')[0]

  const run = async () => {
    setRunning(true)
    setError('')
    try {
      const result = await api.investigate(id, mode)
      setInvestigations((prev) => [result, ...prev])
      setSelected(0)
      setTab('analysis')
    } catch (err) {
      setError(err.message)
    } finally {
      setRunning(false)
    }
  }

  return (
    <div className="page">
      <Link to="/" className="back"><Icon name="arrowLeft" size={14} /> All incidents</Link>
      <div className="page-header">
        <div>
          <div className="eyebrow">
            <span className="mono">INC-{incident.id}</span>·
            <span>{incident.system}</span>·
            <span className="mono">{service?.name}</span>·
            <span>{formatDate(incident.created_at)}</span>
            <Severity level={incident.severity} />
            <span className="pill accent">RCAEval</span>
          </div>
          <h1>{incident.title}</h1>
          <p className="muted">{incident.description}</p>
        </div>
        <div className="header-actions">
          {canInvestigate ? (
            <>
              <div className="segmented" role="group" aria-label="Investigation mode">
                {MODES.map((m) => (
                  <button key={m.value} className={mode === m.value ? 'active' : ''} onClick={() => setMode(m.value)} disabled={running} title={m.hint}>
                    {m.label}
                  </button>
                ))}
              </div>
              <button className="btn primary" onClick={run} disabled={running}>
                {running ? <Spinner /> : <Icon name="play" size={14} />}
                {running ? 'Investigating…' : 'Run root-cause analysis'}
              </button>
            </>
          ) : (
            <span className="pill neutral">Analyst role required to run analysis</span>
          )}
        </div>
      </div>

      {error && <div className="alert error"><Icon name="alert" />{error}</div>}
      {running && (
        <div className="alert info"><Spinner /> The AI agent is reading metrics, logs and traces to find the faulty service. This usually takes 15–60 seconds.</div>
      )}

      <div className="tabs" role="tablist">
        <button role="tab" aria-selected={tab === 'analysis'} className={`tab ${tab === 'analysis' ? 'active' : ''}`} onClick={() => setTab('analysis')}>
          <Icon name="sparkle" /> Analysis <span className="count">{investigations.length}</span>
        </button>
        <button role="tab" aria-selected={tab === 'telemetry'} className={`tab ${tab === 'telemetry' ? 'active' : ''}`} onClick={() => setTab('telemetry')}>
          <Icon name="activity" /> Raw data
        </button>
        {current && (
          <button role="tab" aria-selected={tab === 'trace'} className={`tab ${tab === 'trace' ? 'active' : ''}`} onClick={() => setTab('trace')}>
            <Icon name="route" /> How the agent worked <span className="count">{current.trace.length}</span>
          </button>
        )}
      </div>

      {tab === 'analysis' && (
        <section className="card">
          <div className="card-header">
            <div className="card-title">
              <Icon name="sparkle" />
              <h2>Root-cause analysis</h2>
              {current && showLabel && <Verdict correct={current.predicted_cause === truth} />}
            </div>
            {investigations.length > 1 && (
              <select value={selected} onChange={(e) => setSelected(Number(e.target.value))} aria-label="Investigation run">
                {investigations.map((item, index) => (
                  <option key={item.id} value={index}>
                    Run #{item.id} · {item.method === 'hybrid' ? 'AI + ML' : 'AI only'} · {item.usage.origin === 'evaluation' ? 'benchmark evaluation' : formatDate(item.created_at)}
                  </option>
                ))}
              </select>
            )}
          </div>

          {!current && (
            <div className="steps" style={{ padding: '8px 0' }}>
              <div className="step"><span className="step-num">1</span><div><strong>Look at the raw data</strong><p>The <em>Raw data</em> tab shows which services behaved unusually after the alert.</p></div></div>
              <div className="step"><span className="step-num">2</span><div><strong>Run the AI analysis</strong><p>{canInvestigate ? <>Pick a mode at the top right and select <em>Run root-cause analysis</em>.</> : 'An analyst or admin can start an analysis.'}</p></div></div>
              <div className="step"><span className="step-num">3</span><div><strong>Check the answer</strong><p>Read the verdict and its evidence, then reveal the true answer below.</p></div></div>
            </div>
          )}
          {current && <AgentReport investigation={current} />}

          <div className="label-reveal">
            <button className="link" onClick={() => setShowLabel(!showLabel)}>
              <Icon name={showLabel ? 'x' : 'check'} size={14} />
              {showLabel ? 'Hide' : 'Reveal'} the true answer
            </button>
            {showLabel && <span className="mono strong">{incident.root_cause}</span>}
            {!showLabel && <span className="muted small">Hidden from the agent. Reveal it to check the result.</span>}
          </div>
        </section>
      )}

      {tab === 'telemetry' && (
        <>
          {telemetry && telemetry.nodes.length > 1 && (
            <section className="card" style={{ marginBottom: 16 }}>
              <div className="card-header">
                <div className="card-title"><Icon name="graph" /><h2>Which services look unusual?</h2></div>
              </div>
              <p className="hint">
                Each box is a service, and arrows show which service calls which. Darker boxes changed more after the alert.
                {current && ' The red outline marks the service the agent blamed.'} Hover a box for details.
              </p>
              <ServiceGraph
                nodes={telemetry.nodes}
                edges={telemetry.edges}
                entry={telemetry.entry}
                predicted={current ? current.predicted_cause : null}
              />
            </section>
          )}

          <div className="grid-2">
            <section className="card">
              <div className="card-header">
                <div className="card-title"><Icon name="activity" /><h2>Biggest metric changes</h2></div>
              </div>
              {telemetry && (
                <>
                  <p className="hint">
                    How unusual each metric was after the alert compared with before (0 = normal, 100 = extreme).
                    {current && ' Blue bars belong to the blamed service.'}
                    <Info text="Technically a robust z-score: how many 'normal spreads' the value moved, capped at 100." />
                  </p>
                  <BarList
                    rows={telemetry.anomalies.map((a) => ({ label: a.id.replace('MET:', ''), value: a.z, ...a }))}
                    max={100}
                    format={(v) => v.toFixed(0)}
                    highlight={current ? (row) => row.service === current.predicted_cause : undefined}
                    tooltip={(row) => <><strong>{row.label}</strong>z = {row.z} · trending {row.dir}<div>service: {row.service}</div></>}
                  />
                </>
              )}
            </section>

            <section className="card">
              <div className="card-header">
                <div className="card-title"><Icon name="file" /><h2>New and error log messages</h2></div>
              </div>
              <p className="hint">Log messages that never appeared before the alert, or that contain errors.</p>
              {incident.logs.length === 0 && <p className="muted">No notable log lines.</p>}
              <ol className="logs">
                {incident.logs.map((line, index) => (
                  <li key={index}>
                    <span className="evidence-id">LOG-{index + 1}</span>
                    <code>{line}</code>
                  </li>
                ))}
              </ol>
            </section>
          </div>
        </>
      )}

      {tab === 'trace' && current && (
        <section className="card">
          <div className="card-header">
            <div className="card-title"><Icon name="route" /><h2>How the agent worked</h2></div>
            <span className="muted small">{current.usage.tool_calls} data lookups · {current.usage.latency_s}s</span>
          </div>
          <p className="hint">Each step is one action the AI agent chose to take, in order.</p>
          <AgentTrace trace={current.trace} />
        </section>
      )}
    </div>
  )
}
