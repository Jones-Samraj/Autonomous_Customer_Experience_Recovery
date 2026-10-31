import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { tokenStore } from './api'
import { useAuth } from './auth'

export interface LiveEvent { type: string; [k: string]: any }
interface LiveCtx { connected: boolean; recent: LiveEvent[]; running: string | null }
const Ctx = createContext<LiveCtx>({ connected: false, recent: [], running: null })

/** WebSocket connection with back-off reconnect; server events refresh the relevant queries. */
export function LiveProvider({ children }: { children: ReactNode }) {
  const { user } = useAuth()
  const qc = useQueryClient()
  const [connected, setConnected] = useState(false)
  const [recent, setRecent] = useState<LiveEvent[]>([])
  const [running, setRunning] = useState<string | null>(null)
  const timer = useRef<number | undefined>(undefined)

  useEffect(() => {
    if (!user) return
    let ws: WebSocket | null = null
    let closed = false
    let attempt = 0
    const refresh = () => {
      window.clearTimeout(timer.current)
      timer.current = window.setTimeout(() => qc.invalidateQueries(), 600)
    }
    const connect = () => {
      const token = tokenStore.get()
      if (!token || closed) return
      const proto = location.protocol === 'https:' ? 'wss' : 'ws'
      ws = new WebSocket(`${proto}://${location.host}/api/ws?token=${encodeURIComponent(token)}`)
      ws.onopen = () => { attempt = 0; setConnected(true) }
      ws.onmessage = (m) => {
        try {
          const ev: LiveEvent = JSON.parse(m.data)
          setRecent((r) => [ev, ...r].slice(0, 30))
          if (ev.type === 'agent_event') setRunning(ev.status === 'running' ? ev.agent : null)
          if (ev.type !== 'agent_event' || ev.status !== 'running') refresh()
        } catch { /* ignore malformed frames */ }
      }
      ws.onclose = () => {
        setConnected(false)
        if (!closed) window.setTimeout(connect, Math.min(15000, 1000 * 2 ** attempt++))
      }
    }
    connect()
    return () => { closed = true; window.clearTimeout(timer.current); ws?.close() }
  }, [user, qc])

  return <Ctx.Provider value={{ connected, recent, running }}>{children}</Ctx.Provider>
}

export const useLive = () => useContext(Ctx)
