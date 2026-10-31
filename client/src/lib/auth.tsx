import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { api, get, setUnauthorizedHandler, tokenStore } from './api'
import type { Role, User } from './types'

interface AuthCtx {
  user: User | null
  loading: boolean
  login: (email: string, password: string) => Promise<void>
  logout: () => void
  can: (...roles: Role[]) => boolean
}

const Ctx = createContext<AuthCtx | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(true)
  const qc = useQueryClient()

  const logout = useCallback(() => {
    tokenStore.clear()
    setUser(null)
    qc.clear()
  }, [qc])

  useEffect(() => {
    setUnauthorizedHandler(logout)
    if (!tokenStore.get()) { setLoading(false); return }
    get<User>('/auth/me').then(setUser).catch(() => tokenStore.clear()).finally(() => setLoading(false))
  }, [logout])

  const login = useCallback(async (email: string, password: string) => {
    const body = new URLSearchParams({ username: email, password })
    const r = await api.post('/auth/login', body, { headers: { 'Content-Type': 'application/x-www-form-urlencoded' } })
    tokenStore.set(r.data.access_token)
    setUser(r.data.user)
  }, [])

  // mirrors the server: approvers can do everything analysts can; admins can do everything
  const can = useCallback((...roles: Role[]) => !!user && (user.role === 'admin' || roles.includes(user.role) || (user.role === 'approver' && roles.includes('analyst'))), [user])
  const value = useMemo(() => ({ user, loading, login, logout, can }), [user, loading, login, logout, can])
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function useAuth() {
  const c = useContext(Ctx)
  if (!c) throw new Error('useAuth outside AuthProvider')
  return c
}
