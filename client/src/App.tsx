import { lazy, Suspense, type ReactNode } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import { useAuth } from './lib/auth'
import type { Role } from './lib/types'
import AppShell from './components/AppShell'
import { Spinner } from './components/ui'
import { Toaster } from './components/toast'
import Login from './pages/Login'

const Overview = lazy(() => import('./pages/Overview'))
const Signals = lazy(() => import('./pages/Signals'))
const Issues = lazy(() => import('./pages/Issues'))
const Investigations = lazy(() => import('./pages/Investigations'))
const Impact = lazy(() => import('./pages/Impact'))
const Interventions = lazy(() => import('./pages/Interventions'))
const Approvals = lazy(() => import('./pages/Approvals'))
const Monitoring = lazy(() => import('./pages/Monitoring'))
const Simulator = lazy(() => import('./pages/Simulator'))
const Evaluation = lazy(() => import('./pages/Evaluation'))
const HistoryPage = lazy(() => import('./pages/History'))

/** Route guard: redirects to "/" when the user lacks the required role. */
function RoleGuard({ minRole, children }: { minRole: Role; children: ReactNode }) {
  const { can } = useAuth()
  if (!can(minRole)) return <Navigate to="/" replace />
  return <>{children}</>
}

export default function App() {
  const { user, loading } = useAuth()
  if (loading) return <div className="grid h-full place-items-center"><Spinner label="Starting" /></div>
  if (!user) return <Routes><Route path="*" element={<Login />} /></Routes>
  return (
    <>
      <Toaster />
      <Suspense fallback={<div className="grid h-full place-items-center"><Spinner /></div>}>
        <Routes>
          <Route element={<AppShell />}>
            {/* Open to all authenticated roles */}
            <Route index element={<Overview />} />
            <Route path="signals" element={<Signals />} />
            <Route path="issues" element={<Issues />} />
            <Route path="investigations" element={<Investigations />} />
            <Route path="investigations/:id" element={<Investigations />} />
            <Route path="impact" element={<Impact />} />
            <Route path="evaluation" element={<Evaluation />} />

            {/* Analyst+ only */}
            <Route path="interventions" element={<RoleGuard minRole="analyst"><Interventions /></RoleGuard>} />
            <Route path="monitoring" element={<RoleGuard minRole="analyst"><Monitoring /></RoleGuard>} />
            <Route path="simulator" element={<RoleGuard minRole="analyst"><Simulator /></RoleGuard>} />
            <Route path="history" element={<RoleGuard minRole="analyst"><HistoryPage /></RoleGuard>} />

            {/* Approver+ only */}
            <Route path="approvals" element={<RoleGuard minRole="approver"><Approvals /></RoleGuard>} />

            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
        </Routes>
      </Suspense>
    </>
  )
}
