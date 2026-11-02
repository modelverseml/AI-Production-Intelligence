import { useState } from 'react'

export default function useTooltip() {
  const [tip, setTip] = useState(null)
  const show = (event, content) => setTip({ x: event.clientX, y: event.clientY, content })
  const hide = () => setTip(null)
  const node = tip && (
    <div className="tooltip" style={{ left: tip.x, top: tip.y }} role="tooltip">{tip.content}</div>
  )
  return { show, hide, node }
}
