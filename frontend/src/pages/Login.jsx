import { useState } from 'react'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'
import { api } from '../api'
import { useAuth } from '../auth'
import Icon from '../components/icons'
import { Spinner } from '../components/ui'

const POINTS = [
  { icon: 'sparkle', text: 'An AI agent reads your metrics, logs and traces the way an on-call engineer would.' },
  { icon: 'shield', text: 'It shows the evidence for every claim, and checks that the evidence is real.' },
  { icon: 'chart', text: 'Tested on real outages from a public research benchmark.' },
]

export default function Login() {
  const { user, login } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [mode, setMode] = useState('login')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState(false)

  if (user) return <Navigate to={location.state?.from?.pathname || '/'} replace />

  const submit = async (event) => {
    event.preventDefault()
    setError('')
    setNotice('')
    setBusy(true)
    try {
      if (mode === 'register') {
        await api.register(email, password)
        setNotice('Account created with the viewer role. Sign in to continue.')
        setMode('login')
      } else {
        await login(email, password)
        navigate(location.state?.from?.pathname || '/', { replace: true })
      }
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="login-page">
      <section className="login-hero">
        <div className="brand">
          <span className="brand-mark"><Icon name="activity" size={17} /></span>
          Incident Intelligence
        </div>
        <div>
          <h2>When something breaks, find out which service caused it.</h2>
          <p>Incident Intelligence investigates outages in apps made of many small services and names the one at fault.</p>
          <ul className="hero-points">
            {POINTS.map((point) => (
              <li key={point.icon}><Icon name={point.icon} size={18} /> {point.text}</li>
            ))}
          </ul>
        </div>
        <div className="hero-foot">LangGraph · Azure OpenAI · LightGBM · Hybrid RAG · FastAPI · PostgreSQL</div>
      </section>

      <section className="login-panel">
        <form className="card login-card" onSubmit={submit}>
          <div>
            <h1>{mode === 'login' ? 'Welcome back' : 'Create an account'}</h1>
            <p className="muted">{mode === 'login' ? 'Sign in to investigate incidents.' : 'New accounts start with the viewer role.'}</p>
          </div>
          <label>
            Email
            <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required autoComplete="email" />
          </label>
          <label>
            Password
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              minLength={mode === 'register' ? 10 : undefined}
              autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
            />
          </label>
          {error && <div className="alert error">{error}</div>}
          {notice && <div className="alert info">{notice}</div>}
          <button className="btn primary" disabled={busy}>
            {busy && <Spinner />}
            {mode === 'login' ? 'Sign in' : 'Create account'}
          </button>
          <button
            type="button"
            className="link"
            style={{ justifyContent: 'center' }}
            onClick={() => { setMode(mode === 'login' ? 'register' : 'login'); setError('') }}
          >
            {mode === 'login' ? 'Need an account? Register' : 'Have an account? Sign in'}
          </button>
        </form>
      </section>
    </div>
  )
}
