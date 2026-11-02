const API_URL = import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000/api'
const TOKEN_KEY = 'incident_token'

export const tokenStore = {
  get: () => localStorage.getItem(TOKEN_KEY),
  set: (token) => localStorage.setItem(TOKEN_KEY, token),
  clear: () => localStorage.removeItem(TOKEN_KEY),
}

export class ApiError extends Error {
  constructor(status, message) {
    super(message)
    this.status = status
  }
}

async function request(path, { method = 'GET', body } = {}) {
  const headers = { 'Content-Type': 'application/json' }
  const token = tokenStore.get()
  if (token) headers.Authorization = `Bearer ${token}`

  const response = await fetch(`${API_URL}${path}`, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
  })

  if (response.status === 401 && token) {
    tokenStore.clear()
    window.dispatchEvent(new Event('auth:expired'))
  }

  const data = await response.json().catch(() => null)
  if (!response.ok) {
    const detail = data?.detail
    const message = Array.isArray(detail)
      ? detail.map((item) => item.msg).join(', ')
      : detail || `Request failed (${response.status})`
    throw new ApiError(response.status, message)
  }
  return data
}

export const api = {
  login: (email, password) => request('/auth/login', { method: 'POST', body: { email, password } }),
  register: (email, password) => request('/auth/register', { method: 'POST', body: { email, password } }),
  me: () => request('/auth/me'),
  services: () => request('/services'),
  incidents: () => request('/incidents'),
  incident: (id) => request(`/incidents/${id}`),
  investigations: (id) => request(`/investigations/${id}`),
  investigate: (id, mode) => request(`/investigations/${id}${mode ? `?mode=${mode}` : ''}`, { method: 'POST' }),
  evaluations: () => request('/evaluations'),
  stats: () => request('/stats'),
  telemetry: (id) => request(`/incidents/${id}/telemetry`),
  users: () => request('/users'),
  updateRole: (id, role) => request(`/users/${id}/role`, { method: 'PATCH', body: { role } }),
}
