import Icon from './icons'
import { ConfidenceBar, Info } from './ui'
import EvidenceList from './EvidenceList'

const FAULT_LABELS = {
  cpu: 'CPU stress',
  mem: 'Memory stress / leak',
  disk: 'Disk I/O stress',
  socket: 'Socket exhaustion',
  delay: 'Network delay',
  loss: 'Packet loss',
  code: 'Code defect',
  unknown: 'Unknown fault type',
}

export default function AgentReport({ investigation }) {
  const { report, verification, usage } = investigation
  const ranked = report.ranked_services || []
  const extra = (report.final_ranking || []).filter((s) => !ranked.some((r) => r.service === s))
  const fillSource = investigation.method === 'hybrid' ? 'ML ranker' : 'statistical baseline'

  const fault = (FAULT_LABELS[report.fault_type] || report.fault_type).toLowerCase()
  const percent = Math.round(investigation.confidence * 100)

  return (
    <>
      <div className="verdict">
        <Icon name="sparkle" size={20} />
        <div>
          The AI agent thinks <span className="mono">{investigation.predicted_cause}</span> caused this incident
          {report.fault_type !== 'unknown' && <>, most likely through <strong>{fault}</strong></>}.
          It is {percent}% sure, and {verification.grounded
            ? <>all {verification.cited} pieces of evidence it cited were checked and are real.</>
            : <>{verification.invalid} of its citations could not be verified, so treat this finding with care.</>}
        </div>
      </div>

      <div className="hero-finding">
        <div>
          <div className="label">Faulty service <Info text="The service the agent believes started the incident. Other services may look unhealthy only because they depend on it." /></div>
          <div className="finding-cause mono">{investigation.predicted_cause}</div>
          <span className="pill accent" style={{ marginTop: 6 }}><Icon name="cpu" />{FAULT_LABELS[report.fault_type] || report.fault_type}</span>
        </div>
        <div>
          <div className="label">How sure the agent is <Info text="The agent's own estimate that its #1 pick is correct." /></div>
          <ConfidenceBar value={investigation.confidence} />
        </div>
        <div>
          <div className="label">Evidence check <Info text="Every citation is matched against what the agent's tools actually returned. Made-up citations are rejected and the agent has to fix its report." /></div>
          {verification.grounded ? (
            <span className="pill good"><Icon name="shield" />{verification.cited} citations verified</span>
          ) : (
            <span className="pill bad"><Icon name="x" />{verification.invalid} unverified citations</span>
          )}
          {verification.retries > 0 && (
            <div className="muted small" style={{ marginTop: 6 }}>Fixed its report after {verification.retries} rejection(s)</div>
          )}
        </div>
      </div>

      <h3>What happened</h3>
      <p className="explanation">{report.summary}</p>
      {report.remediation && (
        <div className="callout small"><strong>Suggested fix: </strong><span className="text-2">{report.remediation}</span></div>
      )}

      <h3>Suspects, most likely first <Info text="The agent ranks five services. Under each one: why it was ranked there, and the evidence it used. MET = metric, LOG = logs, TRC = request traces." /></h3>
      <ol className="candidates">
        {ranked.map((item, index) => (
          <li key={item.service} className={`candidate ${index === 0 ? 'top' : ''}`}>
            <span className="rank">{index + 1}</span>
            <div>
              <div className="candidate-head">
                <span className="mono strong">{item.service}</span>
                <ConfidenceBar value={item.likelihood} />
              </div>
              <p>{item.rationale}</p>
              <div className="chips">
                {item.evidence_ids.map((eid) => <span key={eid} className="evidence-id">{eid}</span>)}
              </div>
            </div>
          </li>
        ))}
        {extra.map((service, index) => (
          <li key={service} className="candidate filled">
            <span className="rank">{ranked.length + index + 1}</span>
            <div className="candidate-head">
              <span className="mono">{service}</span>
              <span className="muted small">added from the {fillSource} (the agent listed fewer than 5)</span>
            </div>
          </li>
        ))}
      </ol>

      <div className="grid-2" style={{ marginTop: 20 }}>
        <div>
          <h3>Runbooks used <Info text="Troubleshooting guides the agent found by searching the runbook library." /></h3>
          <EvidenceList docs={investigation.evidence} />
        </div>
        <div>
          <h3>About this analysis</h3>
          <dl className="metrics">
            <div><dt>mode</dt><dd className="small-dd">{investigation.method === 'hybrid' ? 'AI agent + ML model' : 'AI agent only'}</dd></div>
            <div><dt>AI model</dt><dd className="small-dd mono">{usage.deployment}</dd></div>
            <div><dt>data lookups</dt><dd>{usage.tool_calls}</dd></div>
            <div><dt>text processed (tokens)</dt><dd className="small-dd">{((usage.prompt_tokens || 0) + (usage.completion_tokens || 0)).toLocaleString()}</dd></div>
            <div><dt>cost (estimate)</dt><dd>${usage.cost_usd?.toFixed(4)}</dd></div>
            <div><dt>time taken</dt><dd>{usage.latency_s}s</dd></div>
          </dl>
        </div>
      </div>
    </>
  )
}
