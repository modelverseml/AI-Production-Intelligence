import { useEffect, useState } from 'react'
import { api } from '../api'
import { useAuth } from '../auth'

const ROLES = ['viewer', 'analyst', 'admin']

export default function Users() {
  const { user: me } = useAuth()
  const [users, setUsers] = useState([])
  const [error, setError] = useState('')

  useEffect(() => {
    api.users().then(setUsers).catch((err) => setError(err.message))
  }, [])

  const changeRole = async (id, role) => {
    setError('')
    try {
      const updated = await api.updateRole(id, role)
      setUsers((prev) => prev.map((u) => (u.id === id ? updated : u)))
    } catch (err) {
      setError(err.message)
    }
  }

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1>Users</h1>
          <p className="muted">Viewers can read incidents. Analysts and admins can run investigations.</p>
        </div>
      </div>
      {error && <div className="alert error">{error}</div>}
      <div className="card table-card">
        <table>
          <thead><tr><th>ID</th><th>Email</th><th>Role</th></tr></thead>
          <tbody>
            {users.map((u) => (
              <tr key={u.id}>
                <td className="mono">{u.id}</td>
                <td>{u.email}</td>
                <td>
                  <select value={u.role} disabled={u.id === me.id} onChange={(e) => changeRole(u.id, e.target.value)}>
                    {ROLES.map((role) => <option key={role} value={role}>{role}</option>)}
                  </select>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
