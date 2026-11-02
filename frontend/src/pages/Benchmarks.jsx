import { useEffect, useState } from 'react'
import { api } from '../api'
import BarList from '../components/BarList'
import Icon from '../components/icons'
import { Info, Spinner, Stat } from '../components/ui'
import useTooltip from '../useTooltip'

const METHOD_LABELS = {
  baro: 'Simple statistics (baseline)',
  ranker: 'ML model (LightGBM)',
  agent: 'AI agent only',
  hybrid: 'AI agent + ML model',
  ranker_case_cv: 'ML model · easy test (optimistic)',
  ranker_cv: 'ML model · unseen faulty services',
  ranker_loso: 'ML model · unseen application',
}
const METRICS = [
  { value: 'AC@1', label: 'Top-1 accuracy', short: 'Top-1', means: 'ranked the true faulty service #1' },
  { value: 'AC@3', label: 'Top-3 accuracy', short: 'Top-3', means: 'had the true faulty service in its top 3' },
  { value: 'Avg@5', label: 'Average top-5 score', short: 'Top-5 avg', means: 'scored on how high it ranked the true faulty service (average of top-1 … top-5 accuracy)' },
]
const GLOSSARY = [
  ['RCAEval', 'A public research benchmark. Researchers broke one service at a time in three real demo applications and recorded what happened.'],
  ['Top-1 accuracy', "How often the method's #1 suspect was the service that was actually broken."],
  ['Simple statistics (baseline)', 'Blame whichever service had the most unusual metric. This is the bar to beat.'],
  ['ML model (LightGBM)', 'A model trained on past incidents to rank suspects. It is always tested on incidents it never saw.'],
  ['AI agent', 'A language model (Azure OpenAI) that investigates like an engineer: it looks up metrics, logs and traces, then writes a report.'],
  ['Held-out cases', 'Incidents never used while building or tuning the system, so the scores are not inflated.'],
]
// Score thresholds for the sequential heat ramp (validated ordinal blue).
const HEAT_STEPS = [0.5, 0.65, 0.8, 0.9, 0.97]

function pct(value) {
  return value === undefined || value === null ? '—' : `${(value * 100).toFixed(1)}%`
}

function heatLevel(value) {
  let level = -1
  HEAT_STEPS.forEach((step, i) => { if (value >= step) level = i })
  return level
}

function HeatTable({ methods, metric }) {
  const { show, hide, node } = useTooltip()
  const names = Object.keys(methods)
  const datasets = Object.keys(methods[names[0]] || {})
  return (
    <>
      <div className="table-card card">
        <table className="heat">
          <thead>
            <tr>
              <th>Method</th>
              {datasets.map((ds) => <th key={ds} style={{ textAlign: 'center' }}>{ds === 'overall' ? 'Overall' : ds}</th>)}
            </tr>
          </thead>
          <tbody>
            {names.map((name) => (
              <tr key={name}>
                <td className="strong">{METHOD_LABELS[name] || name}</td>
                {datasets.map((ds) => {
                  const cell = methods[name][ds]
                  const value = cell?.[metric]
                  const level = value === undefined ? -1 : heatLevel(value)
                  return (
                    <td
                      key={ds}
                      className="heat-cell"
                      style={{
                        background: level < 0 ? 'transparent' : `var(--seq-${level})`,
                        color: level < 0 ? 'var(--text)' : level <= 1 ? '#0b0b0b' : '#ffffff',
                      }}
                      onMouseMove={(e) => show(e, <><strong>{METHOD_LABELS[name] || name}</strong>{ds === 'overall' ? 'All datasets' : ds}: {pct(value)}<div>out of {cell?.cases} incidents</div></>)}
                      onMouseLeave={hide}
                    >
                      {pct(value)}
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="heat-legend" style={{ marginTop: 8 }}>
        <span>Darker = better:</span>
        <span className="swatch" style={{ background: 'var(--surface-3)' }} /> &lt;{HEAT_STEPS[0] * 100}%
        {HEAT_STEPS.map((step, i) => (
          <span key={step} style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
            <span className="swatch" style={{ background: `var(--seq-${i})` }} />≥{step * 100}%
          </span>
        ))}
      </div>
      {node}
    </>
  )
}

// Agent details shown as readable rows: [label, format].
const AGENT_ROWS = {
  citation_validity: ['Cited evidence that was real', (v) => pct(v)],
  grounded_reports: ['Reports fully verified', (v) => pct(v)],
  self_corrected_reports: ['Reports fixed after the evidence check rejected them', (v) => v],
  fault_type_accuracy: ['Fault type correct (CPU, memory, network, code…)', (v) => pct(v)],
  mean_tool_calls: ['Data lookups per analysis', (v) => v.toFixed(1)],
  cost_per_case_usd: ['Cost per analysis (estimate)', (v) => `$${v.toFixed(4)}`],
  total_cost_usd: ['Total cost of this evaluation', (v) => `$${v.toFixed(2)}`],
  latency_p50_s: ['Typical time per analysis', (v) => `${Math.round(v)}s`],
  latency_p95_s: ['Slowest 5% take longer than', (v) => `${Math.round(v)}s`],
}

const LIVE_LABELS = { agent: 'AI agent only', hybrid: 'AI agent + ML model' }

function LiveEvaluation({ live, metric }) {
  if (!live) return null
  const entries = Object.entries(live.methods)
  return (
    <section className="card">
      <div className="card-header">
        <div className="card-title"><Spinner /><h2>AI agent evaluation in progress</h2></div>
        <span className="muted small">Refreshes every 30 seconds · {live.deployment}</span>
      </div>
      <p className="hint">
        Interim numbers on the outages finished so far. Each method is compared with the ML model and simple statistics
        on exactly the same outages. Final results replace this panel when the run completes.
      </p>
      {entries.map(([method, entry]) => {
        const scores = entry.scores
        return (
          <div key={method} style={{ marginBottom: 18 }}>
            <div className="candidate-head" style={{ marginBottom: 8 }}>
              <strong>{LIVE_LABELS[method]}</strong>
              <span className="muted small">{entry.done} of {entry.target} outages done</span>
              {entry.done > 0 && <span className="pill good"><Icon name="shield" />{pct(entry.grounded_rate)} evidence verified</span>}
              {entry.done > 0 && <span className="muted small">${entry.cost_usd} spent</span>}
            </div>
            <div className="confidence-track" style={{ height: 6, marginBottom: 10 }}>
              <div className="confidence-fill" style={{ width: `${(entry.done / entry.target) * 100}%` }} />
            </div>
            {scores ? (
              <BarList
                rows={[method, 'ranker', 'baro'].filter((m) => scores[m]).map((m) => ({
                  label: m === method ? LIVE_LABELS[method] : METHOD_LABELS[m], key: m, value: scores[m][metric],
                }))}
                max={1}
                format={pct}
                highlight={(row) => row.key === method}
                tooltip={(row) => <><strong>{row.label}</strong>{pct(row.value)} on the same {entry.done} outages</>}
              />
            ) : (
              <p className="muted small">Waiting to start; this begins after the AI-agent-only runs finish.</p>
            )}
          </div>
        )
      })}
    </section>
  )
}

export default function Benchmarks() {
  const [data, setData] = useState(null)
  const [metric, setMetric] = useState('AC@1')
  const [error, setError] = useState('')

  useEffect(() => {
    let timer
    const load = () => api.evaluations()
      .then((result) => {
        setData(result)
        // Keep refreshing while the held-out evaluation is still running.
        const running = !result.rcaeval && Object.values(result.live?.methods || {}).some((m) => m.done < m.target)
        if (running) timer = setTimeout(load, 30000)
      })
      .catch((err) => setError(err.message))
    load()
    return () => clearTimeout(timer)
  }, [])

  if (error) return <div className="page"><div className="alert error">{error}</div></div>
  if (!data) return <div className="page-loading"><Spinner /> Loading benchmarks…</div>

  const { rcaeval, ranker, live } = data
  const overall = rcaeval
    ? Object.entries(rcaeval.methods).map(([m, v]) => ({ label: METHOD_LABELS[m] || m, key: m, value: v.overall[metric] }))
    : []
  const best = Math.max(...overall.map((r) => r.value), 0)
  const hybrid = rcaeval?.llm?.hybrid
  const metricInfo = METRICS.find((m) => m.value === metric)
  const winner = overall.find((r) => r.value === best)
  const baseline = overall.find((r) => r.key === 'baro')
  const rankerOverall = ranker?.methods?.ranker_cv?.overall?.[metric]
  const rankerBaseline = ranker?.methods?.baro?.overall?.[metric]

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1>Benchmarks</h1>
          <p className="muted">
            How often does each method find the service that really broke? Tested on real outages from the{' '}
            <a href="https://arxiv.org/abs/2412.17015" target="_blank" rel="noreferrer">RCAEval</a> research benchmark.
          </p>
        </div>
        <div className="segmented" role="group" aria-label="Score">
          {METRICS.map((m) => (
            <button key={m.value} className={metric === m.value ? 'active' : ''} onClick={() => setMetric(m.value)} title={`${m.label}: ${m.means}`}>{m.short}</button>
          ))}
        </div>
      </div>

      <section className="card" style={{ marginBottom: 20 }}>
        <div className="card-title" style={{ marginBottom: 8 }}><Icon name="sparkle" /><h2 style={{ margin: 0 }}>Key takeaway</h2></div>
        {rcaeval && winner && baseline ? (
          <p className="takeaway" style={{ margin: 0 }}>
            On {rcaeval.cases_scored} held-out outages, <strong>{winner.label}</strong> {metricInfo.means} in{' '}
            <strong>{pct(best)}</strong> of cases, compared with {pct(baseline.value)} for simple statistics.
          </p>
        ) : live?.methods?.agent?.scores ? (
          <p className="takeaway" style={{ margin: 0 }}>
            So far, on {live.methods.agent.done} held-out outages, the <strong>AI agent</strong> {metricInfo.means} in{' '}
            <strong>{pct(live.methods.agent.scores.agent[metric])}</strong> of cases, compared with{' '}
            {pct(live.methods.agent.scores.ranker?.[metric])} for the ML model and {pct(live.methods.agent.scores.baro[metric])} for
            simple statistics. Every piece of evidence it cited was real. (Evaluation still running.)
          </p>
        ) : rankerOverall !== undefined ? (
          <p className="takeaway" style={{ margin: 0 }}>
            On all {ranker.cases} outages, the <strong>ML model</strong> {metricInfo.means} in{' '}
            <strong>{pct(rankerOverall)}</strong> of cases, even for faulty services it never saw during training,
            compared with {pct(rankerBaseline)} for simple statistics. AI agent results appear here once the evaluation finishes.
          </p>
        ) : (
          <p className="muted" style={{ margin: 0 }}>No results yet.</p>
        )}
      </section>

      {rcaeval ? (
        <>
          <div className="stats">
            <Stat icon="check" label={`Best ${metricInfo.label.toLowerCase()}`} value={pct(best)} sub={winner?.label} />
            <Stat icon="layers" label={<>Outages tested <Info text="Held-out incidents: none of them were used while building or tuning the system." /></>}
              value={rcaeval.cases_scored} sub={`${rcaeval.dev_cases_excluded} used for tuning, excluded`} />
            <Stat icon="shield" label={<>Real citations <Info text="Share of the agent's cited evidence that its tools actually returned. 100% means it made nothing up." /></>}
              value={pct(hybrid?.citation_validity)} sub={hybrid ? `${pct(hybrid.grounded_reports)} of reports fully verified` : ''} />
            <Stat icon="dollar" label="Cost per analysis" value={hybrid ? `$${hybrid.cost_per_case_usd.toFixed(3)}` : '—'}
              sub={hybrid ? `about ${Math.round(hybrid.latency_p50_s)}s each · ${rcaeval.deployment}` : ''} />
          </div>

          <div className="dash-grid">
            <section className="card">
              <div className="card-header">
                <div className="card-title"><Icon name="chart" /><h2>{metricInfo.label} by method</h2></div>
              </div>
              <BarList
                rows={overall}
                max={1}
                format={pct}
                highlight={(row) => row.value === best}
              />
            </section>
            <section className="card">
              <div className="card-header">
                <div className="card-title"><Icon name="shield" /><h2>Why these numbers are fair</h2></div>
              </div>
              <ul className="small text-2" style={{ paddingLeft: 18, margin: 0, display: 'flex', flexDirection: 'column', gap: 6 }}>
                <li>Every method is tested on the same {rcaeval.cases_scored} outages.</li>
                <li>The ML model never saw these outages, or even the broken services, during training.</li>
                <li>The AI agent never sees the answer.</li>
                <li>Outages used to tune the AI's instructions are left out.</li>
              </ul>
            </section>
          </div>

          <h2 className="section-title">Results per application</h2>
          <p className="muted small section-sub">OB = Online Boutique (shop), SS = Sock Shop (shop), TT = Train Ticket (booking, 68 services). RE2 = resource and network faults, RE3 = code bugs. Hover a cell for details.</p>
          <HeatTable methods={rcaeval.methods} metric={metric} />

          {Object.keys(rcaeval.llm || {}).length > 0 && (
            <>
              <h2 className="section-title">AI agent details</h2>
              <div className="table-card card">
                <table>
                  <thead><tr><th>Measure</th>{Object.keys(rcaeval.llm).map((m) => <th key={m}>{METHOD_LABELS[m]}</th>)}</tr></thead>
                  <tbody>
                    {Object.entries(AGENT_ROWS).map(([key, [label, format]]) => (
                      <tr key={key}>
                        <td>{label}</td>
                        {Object.keys(rcaeval.llm).map((m) => <td key={m} className="strong">{format(rcaeval.llm[m][key])}</td>)}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </>
      ) : (
        <LiveEvaluation live={live} metric={metric} />
      )}

      {ranker && (
        <>
          <h2 className="section-title">How well the ML model generalizes ({ranker.cases} outages)</h2>
          <p className="muted small section-sub">
            Random guessing would get {pct(ranker['chance_AC@1'])} top-1 accuracy. The rows run from the easiest test to the hardest:
            the last two test on broken services, and on whole applications, that the model never saw during training.
          </p>
          <HeatTable methods={ranker.methods} metric={metric} />
        </>
      )}

      <h2 className="section-title">Glossary</h2>
      <section className="card">
        <dl className="glossary">
          {GLOSSARY.map(([term, meaning]) => (
            <div key={term}><dt>{term}</dt><dd>{meaning}</dd></div>
          ))}
        </dl>
      </section>
    </div>
  )
}
