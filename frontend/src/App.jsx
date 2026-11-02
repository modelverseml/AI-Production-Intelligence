import { Navigate, Route, Routes } from 'react-router-dom'
import { ProtectedRoute } from './auth'
import Layout from './components/Layout'
import Benchmarks from './pages/Benchmarks'
import Dashboard from './pages/Dashboard'
import Incident from './pages/Incident'
import Login from './pages/Login'
import Users from './pages/Users'

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route element={<ProtectedRoute><Layout /></ProtectedRoute>}>
        <Route index element={<Dashboard />} />
        <Route path="incidents/:id" element={<Incident />} />
        <Route path="benchmarks" element={<Benchmarks />} />
        <Route
          path="admin/users"
          element={<ProtectedRoute roles={['admin']}><Users /></ProtectedRoute>}
        />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
