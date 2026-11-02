export default function EvidenceList({ docs }) {
  if (docs.length === 0) return <p className="muted">None cited.</p>
  return (
    <ul className="evidence">
      {docs.map((doc) => (
        <li key={doc.id}>
          <div className="evidence-head">
            <span className="evidence-id">{doc.id}</span>
            <strong>{doc.title}</strong>
          </div>
          <p className="muted small">{doc.snippet}</p>
        </li>
      ))}
    </ul>
  )
}
