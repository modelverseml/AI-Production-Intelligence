import { ANOMALY_STEPS, anomalyLevel } from '../theme'
import useTooltip from '../useTooltip'

const NODE_W = 156
const NODE_H = 34
const COL_GAP = 64
const ROW_GAP = 14
const PAD = 16
const MAX_ROWS = 6

/** Layered layout: depth = longest call path from a root (cycles broken by visit order). */
function layout(nodes, edges, entry) {
  const ids = nodes.map((n) => n.id)
  const out = Object.fromEntries(ids.map((id) => [id, []]))
  const indegree = Object.fromEntries(ids.map((id) => [id, 0]))
  edges.forEach(([a, b]) => {
    if (out[a] && b in indegree && a !== b) {
      out[a].push(b)
      indegree[b] += 1
    }
  })
  const depth = {}
  const roots = ids.filter((id) => indegree[id] === 0)
  const queue = (roots.includes(entry) ? [entry, ...roots.filter((r) => r !== entry)] : roots).map((id) => [id, 0])
  const visits = {}
  while (queue.length) {
    const [id, d] = queue.shift()
    if ((depth[id] ?? -1) >= d) continue
    visits[id] = (visits[id] || 0) + 1
    if (visits[id] > ids.length) continue
    depth[id] = d
    out[id].forEach((next) => queue.push([next, d + 1]))
  }
  ids.forEach((id) => { if (depth[id] === undefined) depth[id] = 0 })

  const columns = {}
  ids.forEach((id) => { (columns[depth[id]] ||= []).push(id) })
  const score = Object.fromEntries(nodes.map((n) => [n.id, n.score]))
  Object.values(columns).forEach((col) => col.sort((a, b) => score[b] - score[a]))

  // Wrap tall layers into extra visual columns so the graph stays readable.
  const visual = []
  Object.keys(columns).map(Number).sort((a, b) => a - b).forEach((d) => {
    for (let i = 0; i < columns[d].length; i += MAX_ROWS) visual.push(columns[d].slice(i, i + MAX_ROWS))
  })
  const positions = {}
  const tallest = Math.max(...visual.map((c) => c.length))
  const height = PAD * 2 + tallest * NODE_H + (tallest - 1) * ROW_GAP
  visual.forEach((col, c) => {
    const colHeight = col.length * NODE_H + (col.length - 1) * ROW_GAP
    const top = (height - colHeight) / 2
    col.forEach((id, i) => {
      positions[id] = { x: PAD + c * (NODE_W + COL_GAP), y: top + i * (NODE_H + ROW_GAP) }
    })
  })
  const width = PAD * 2 + visual.length * (NODE_W + COL_GAP) - COL_GAP
  return { positions, width, height }
}

function shorten(name) {
  return name.length > 21 ? `${name.slice(0, 20)}…` : name
}

export default function ServiceGraph({ nodes, edges, entry, predicted }) {
  const { show, hide, node: tooltip } = useTooltip()
  const { positions, width, height } = layout(nodes, edges, entry)
  const byId = Object.fromEntries(nodes.map((n) => [n.id, n]))

  return (
    <div>
      <div className="graph-wrap">
        <svg className="graph-svg" width={width} height={height} viewBox={`0 0 ${width} ${height}`} role="img"
          aria-label="Service dependency graph shaded by anomaly score">
          <defs>
            <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
              <path d="M0 0 10 5 0 10z" fill="var(--border-strong)" />
            </marker>
          </defs>
          {edges.map(([a, b]) => {
            const from = positions[a]
            const to = positions[b]
            if (!from || !to) return null
            const x1 = from.x + NODE_W
            const y1 = from.y + NODE_H / 2
            const x2 = to.x
            const y2 = to.y + NODE_H / 2
            const backward = x2 <= x1
            const path = backward
              ? `M${from.x + NODE_W / 2} ${from.y + NODE_H} C ${from.x + NODE_W / 2} ${from.y + NODE_H + 30}, ${to.x + NODE_W / 2} ${to.y + NODE_H + 30}, ${to.x + NODE_W / 2} ${to.y + NODE_H}`
              : `M${x1} ${y1} C ${x1 + COL_GAP / 2} ${y1}, ${x2 - COL_GAP / 2} ${y2}, ${x2 - 2} ${y2}`
            const hot = a === predicted || b === predicted
            return <path key={`${a}->${b}`} d={path} className={`graph-edge ${hot ? 'hot' : ''}`} markerEnd="url(#arrow)" />
          })}
          {nodes.map((n) => {
            const pos = positions[n.id]
            const level = anomalyLevel(n.score)
            const fill = level < 0 ? 'var(--surface-3)' : `var(--seq-${level})`
            const ink = level < 0 ? 'var(--text-2)' : level <= 1 ? '#0b0b0b' : '#ffffff'
            const isPredicted = n.id === predicted
            return (
              <g
                key={n.id}
                className={`graph-node ${isPredicted ? 'predicted' : ''}`}
                transform={`translate(${pos.x} ${pos.y})`}
                onMouseMove={(e) => show(e, (
                  <>
                    <strong>{n.id}</strong>
                    unusualness {byId[n.id].score.toFixed(0)} / 100
                    {n.id === entry && <div>where users see the problem</div>}
                    {isPredicted && <div>the agent's predicted root cause</div>}
                  </>
                ))}
                onMouseLeave={hide}
              >
                <rect className="body" width={NODE_W} height={NODE_H} rx="8" fill={fill} />
                {isPredicted && <rect className="ring" x="-4" y="-4" width={NODE_W + 8} height={NODE_H + 8} rx="11" />}
                <text x="12" y={NODE_H / 2 + 4} fill={ink}>{shorten(n.id)}</text>
                {n.id === entry && (
                  <text x={NODE_W - 10} y={NODE_H / 2 + 4} fill={ink} textAnchor="end" style={{ fontSize: 10, opacity: 0.8 }}>entry</text>
                )}
              </g>
            )
          })}
        </svg>
      </div>
      <div className="graph-legend" style={{ marginTop: 12 }}>
        <span>How unusual after the alert:</span>
        <span className="swatch" style={{ background: 'var(--surface-3)' }} /> normal
        {ANOMALY_STEPS.map((step, i) => (
          <span key={step} style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
            <span className="swatch" style={{ background: `var(--seq-${i})` }} />≥{step}
          </span>
        ))}
        {predicted && (
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4, marginLeft: 10 }}>
            <span className="swatch" style={{ border: '2px solid var(--critical)', background: 'transparent' }} /> agent's predicted root cause
          </span>
        )}
      </div>
      {tooltip}
    </div>
  )
}
