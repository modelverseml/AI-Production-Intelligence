import useTooltip from '../useTooltip'

/**
 * Horizontal single-series bar chart. Bars share one baseline; the value is
 * labeled at the tip, and each row has a hover tooltip.
 */
export default function BarList({ rows, max, format = (v) => v, highlight, tooltip }) {
  const { show, hide, node } = useTooltip()
  const top = max ?? Math.max(...rows.map((r) => r.value), 1)
  return (
    <div className="barlist">
      {rows.map((row) => (
        <div
          key={row.label}
          className="barlist-row"
          onMouseMove={(e) => show(e, tooltip ? tooltip(row) : <><strong>{row.label}</strong>{format(row.value)}</>)}
          onMouseLeave={hide}
        >
          <span className="barlist-label" title={row.label}>{row.label}</span>
          <div className="barlist-track">
            <div
              className={`barlist-bar ${highlight && !highlight(row) ? 'dim' : ''}`}
              style={{ width: `${Math.max(0, Math.min(1, row.value / top)) * 100}%` }}
            />
          </div>
          <span className="barlist-value">{format(row.value)}</span>
        </div>
      ))}
      {node}
    </div>
  )
}
