import { useState } from 'react'
import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth'
import { applyTheme, currentTheme } from '../theme'
import Icon from './icons'

export default function Layout() {
  const { user, logout, hasRole } = useAuth()
  const navigate = useNavigate()
  const [theme, setTheme] = useState(currentTheme)

  const toggleTheme = () => {
    const next = theme === 'dark' ? 'light' : 'dark'
    applyTheme(next)
    setTheme(next)
  }

  const signOut = () => {
    logout()
    navigate('/login')
  }

  return (
    <div className="shell">
      <aside className="sidebar">
        <NavLink to="/" className="brand">
          <span className="brand-mark"><Icon name="activity" size={17} /></span>
          <span>
            Incident Intelligence
            <small>Agentic root-cause analysis</small>
          </span>
        </NavLink>

        <div className="nav-label">Operate</div>
        <NavLink to="/" end className="nav-item">
          <Icon name="alert" /> <span>Incidents</span>
        </NavLink>
        <NavLink to="/benchmarks" className="nav-item">
          <Icon name="chart" /> <span>Benchmarks</span>
        </NavLink>
        {hasRole('admin') && (
          <>
            <div className="nav-label">Admin</div>
            <NavLink to="/admin/users" className="nav-item">
              <Icon name="users" /> <span>Users</span>
            </NavLink>
          </>
        )}

        <div className="sidebar-footer">
          <div className="user-chip">
            <span className="avatar">{user.email[0].toUpperCase()}</span>
            <div className="who">
              <div className="email">{user.email}</div>
              <span className={`role role-${user.role}`}>{user.role}</span>
            </div>
          </div>
          <div className="sidebar-actions">
            <button className="btn ghost" onClick={toggleTheme} aria-label="Toggle color theme">
              <Icon name={theme === 'dark' ? 'sun' : 'moon'} /> <span>{theme === 'dark' ? 'Light' : 'Dark'}</span>
            </button>
            <button className="btn ghost" onClick={signOut}>
              <Icon name="logout" /> <span>Sign out</span>
            </button>
          </div>
        </div>
      </aside>
      <main>
        <Outlet />
      </main>
    </div>
  )
}
