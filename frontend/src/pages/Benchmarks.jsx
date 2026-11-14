import { useEffect, useState } from 'react'
import { api } from '../api'
import BarList from '../components/BarList'
import Icon from '../components/icons'
import { Info, Spinner, Stat } from '../components/ui'
import useTooltip from '../useTooltip'

const METHOD_LABELS = {
  baro: 'Simple statistics',
  ranker: 'ML model',
  agent: 'AI agent',
  hybrid: 'AI agent + ML model',
  ranker_case_cv: 'ML model · easy test',
  ranker_cv: 'ML model · new broken services',
  ranker_loso: 'ML model · new app',
}
// One short line under each row name, so the table explains itself.
const METHOD_NOTES = {
  baro: 'Blames the service whose numbers jumped most. The bar to beat.',
  ranker: 'Trained on past outages to rank the suspects.',
  agent: 'An AI that checks metrics, logs and traces like an engineer.',
  hybrid: 'The AI agent, given the ML model’s suspects as a hint.',
  ranker_case_cv: 'It had seen the same services break in training, so this is flattering.',
  ranker_cv: 'Tested on services it never saw break. The main result.',
  ranker_loso: 'Tested on a whole app it never saw. The hardest test.',
}
const METRICS = [
  { value: 'AC@1', label: 'Right on the first guess', short: 'First guess', means: 'named the broken service as its first guess',
    reads: 'Each % shows how often the method’s first guess was the service that actually broke.' },
  { value: 'AC@3', label: 'Right within 3 guesses', short: 'Top 3 guesses', means: 'had the broken service among its top 3 guesses',
    reads: 'Each % shows how often the service that actually broke was among the method’s top 3 guesses.' },
  { value: 'Avg@5', label: 'Overall ranking score', short: 'Overall score', means: 'scored on how high it ranked the broken service',
    reads: 'Each % is an overall score: higher means the broken service was ranked nearer the top of the suspect list.' },
]
const GLOSSARY = [
  ['RCAEval', 'A public research benchmark. Researchers broke one service at a time in three real demo apps and recorded what happened.'],
  ['Service', 'One small program inside an app, such as “cart” or “payment”. The job is to find which one caused the outage.'],
  ['First guess / top 3 guesses', 'Each method lists its suspects in order. We check whether the broken service was #1, or anywhere in the first three.'],
  ['Fair testing', 'Every method is scored on the same outages, and none of them was used while building or tuning the system.'],
]

function pct(value) {
  return value === undefined || value === null ? '—' : `${(value * 100).toFixed(1)}%`
}

const REFERENCE_ROWS = ['baro']

/** Results table: one row per method with its overall score and a bar, so rows compare at a glance. */
function ScoreTable({ methods, metric, highlight }) {
  const { show, hide, node } = useTooltip()
  return (
    <>
      <div className="table-card card score-table">
        <table>
          <thead>
            <tr><th>Method</th><th>Score</th></tr>
          </thead>
          <tbody>
            {Object.entries(methods).map(([name, rows]) => {
              const label = METHOD_LABELS[name] || name
              const value = rows.overall?.[metric]
              return (
                <tr key={name} className={name === highlight ? 'highlight' : REFERENCE_ROWS.includes(name) ? 'reference' : ''}>
                  <td className="method">
                    <div className="strong">{label}</div>
                    {METHOD_NOTES[name] && <div className="muted small">{METHOD_NOTES[name]}</div>}
                  </td>
                  <td
                    className="score"
                    onMouseMove={(e) => show(e, <><strong>{label}</strong>{pct(value)}<div>out of {rows.overall?.cases} outages</div></>)}
                    onMouseLeave={hide}
                  >
                    <div className="cell-inner">
                      <div className="cell-value">{pct(value)}</div>
                      <div className="cell-track"><div className="cell-fill" style={{ width: `${(value ?? 0) * 100}%` }} /></div>
                    </div>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
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
  const rankerHard = ranker?.methods?.ranker_loso?.overall?.[metric]

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

          <h2 className="section-title">Detailed results</h2>
          <p className="muted small section-sub">{metricInfo.reads}</p>
          <ScoreTable methods={rcaeval.methods} metric={metric} />

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
        <section className="card" style={{ marginTop: 20 }}>
          <div className="card-header">
            <div className="card-title"><Icon name="layers" /><h2>Does the ML model work on outages it has never seen?</h2></div>
            <span className="pill neutral">{ranker.cases} outages</span>
          </div>
          {rankerOverall !== undefined && (
            <p className="takeaway" style={{ margin: '0 0 6px' }}>
              It {metricInfo.means} in <strong>{pct(rankerOverall)}</strong> of outages, compared with {pct(rankerBaseline)} for
              simple statistics{rankerHard !== undefined && <>, and still <strong>{pct(rankerHard)}</strong> on an app it never saw</>}.
            </p>
          )}
          <p className="muted small" style={{ margin: '0 0 14px' }}>
            Outages were hidden from the model during training, then used to test it, in three ways from easiest to hardest.
            {' '}{metricInfo.reads}
          </p>
          <ScoreTable methods={ranker.methods} metric={metric} highlight="ranker_cv" />
        </section>
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
