import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Activity, Bell, ChevronRight, Database, FlaskConical, Gauge, History, LayoutDashboard, LogOut, Microscope, Radar, Route, Search, ShieldCheck, UsersRound, Wifi, WifiOff } from 'lucide-react'
import { get, post } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import { useLive } from '@/lib/live'
import { date, title } from '@/lib/format'
import type { Approval, Notice, Role } from '@/lib/types'
import { Badge, cn } from './ui'
import AiAssistant from './AiAssistant'

const NAV: { to: string; label: string; icon: typeof LayoutDashboard; end?: boolean; badge?: boolean; minRole?: Role }[] = [
  { to: '/', label: 'Executive Overview', icon: LayoutDashboard, end: true },
  { to: '/signals', label: 'Signal Explorer', icon: Database },
  { to: '/issues', label: 'Issue Intelligence', icon: Radar },
  { to: '/investigations', label: 'Root Cause', icon: Microscope },
  { to: '/impact', label: 'Customer Impact', icon: UsersRound },
  { to: '/interventions', label: 'Intervention Center', icon: Route, minRole: 'analyst' },
  { to: '/approvals', label: 'Approval Center', icon: ShieldCheck, badge: true, minRole: 'approver' },
  { to: '/monitoring', label: 'Recovery Monitoring', icon: Activity, minRole: 'analyst' },
  { to: '/simulator', label: 'Jury Simulator', icon: FlaskConical, minRole: 'analyst' },
  { to: '/evaluation', label: 'AI Evaluation', icon: Gauge },
  { to: '/history', label: 'Execution History', icon: History, minRole: 'analyst' },
]
const CRUMBS: Record<string, string> = Object.fromEntries(NAV.map((n) => [n.to.replace('/', ''), n.label]))

function Breadcrumbs() {
  const { pathname } = useLocation()
  const parts = pathname.split('/').filter(Boolean)
  return (
    <nav aria-label="Breadcrumb" className="flex items-center gap-1 text-sm text-muted">
      <Link to="/" className="hover:text-ink">CX Sentinel</Link>
      {parts.map((p, i) => (
        <span key={i} className="flex items-center gap-1">
          <ChevronRight size={14} />
          <span className={i === parts.length - 1 ? 'font-medium text-ink' : ''}>{CRUMBS[p] ?? (/^\d+$/.test(p) ? `#${p}` : title(p))}</span>
        </span>
      ))}
      {!parts.length && <span className="flex items-center gap-1"><ChevronRight size={14} /><span className="font-medium text-ink">Executive Overview</span></span>}
    </nav>
  )
}

function GlobalSearch() {
  const [q, setQ] = useState('')
  const [dq, setDq] = useState('')
  const [open, setOpen] = useState(false)
  const nav = useNavigate()
  const box = useRef<HTMLDivElement>(null)
  useEffect(() => { const t = setTimeout(() => setDq(q.trim()), 250); return () => clearTimeout(t) }, [q])
  useEffect(() => {
    const h = (e: MouseEvent) => { if (!box.current?.contains(e.target as Node)) setOpen(false) }
    document.addEventListener('mousedown', h)
    return () => document.removeEventListener('mousedown', h)
  }, [])
  const res = useQuery({ queryKey: ['search', dq], queryFn: () => get<{ results: { type: string; id: number; title: string; link: string }[] }>('/search', { q: dq }), enabled: dq.length >= 2 })
  return (
    <div ref={box} className="relative w-full max-w-md">
      <Search size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted" />
      <input value={q} onChange={(e) => { setQ(e.target.value); setOpen(true) }} onFocus={() => setOpen(true)} placeholder="Search issues, hypotheses, interventions, evidence..."
        aria-label="Global search" className="h-9 w-full rounded-lg border border-line bg-slate-50 pl-9 pr-3 text-sm placeholder:text-muted focus:border-brand focus:bg-white focus:outline-none focus:ring-2 focus:ring-brand/20" />
      {open && dq.length >= 2 && (
        <div className="absolute z-40 mt-1.5 w-full overflow-hidden rounded-xl border border-line bg-white shadow-lg">
          {res.isLoading && <p className="px-4 py-3 text-xs text-muted">Searching...</p>}
          {res.data?.results.length === 0 && <p className="px-4 py-3 text-xs text-muted">No matches for "{dq}"</p>}
          {res.data?.results.map((r) => (
            <button key={`${r.type}-${r.id}`} onClick={() => { nav(r.link); setOpen(false); setQ('') }} className="flex w-full items-center gap-2 px-4 py-2 text-left text-sm hover:bg-slate-50">
              <Badge tone="neutral">{title(r.type)}</Badge><span className="truncate">{r.title}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

function NotificationCenter() {
  const [open, setOpen] = useState(false)
  const qc = useQueryClient()
  const nav = useNavigate()
  const box = useRef<HTMLDivElement>(null)
  const q = useQuery({ queryKey: ['notifications'], queryFn: () => get<{ unread: number; items: Notice[] }>('/notifications'), refetchInterval: 30000 })
  const read = useMutation({ mutationFn: () => post('/notifications/read'), onSuccess: () => qc.invalidateQueries({ queryKey: ['notifications'] }) })
  useEffect(() => {
    const h = (e: MouseEvent) => { if (!box.current?.contains(e.target as Node)) setOpen(false) }
    document.addEventListener('mousedown', h)
    return () => document.removeEventListener('mousedown', h)
  }, [])
  const dot = { error: 'bg-critical', warning: 'bg-warning', success: 'bg-good', info: 'bg-brand' } as Record<string, string>
  return (
    <div ref={box} className="relative">
      <button onClick={() => setOpen(!open)} aria-label={`Notifications, ${q.data?.unread ?? 0} unread`} className="relative grid size-9 place-items-center rounded-lg text-ink-2 hover:bg-slate-100">
        <Bell size={18} />
        {!!q.data?.unread && <span className="absolute right-1 top-1 grid min-w-4 place-items-center rounded-full bg-critical px-1 text-[10px] font-semibold text-white">{q.data.unread}</span>}
      </button>
      {open && (
        <div className="absolute right-0 z-40 mt-2 w-96 overflow-hidden rounded-xl border border-line bg-white shadow-lg">
          <div className="flex items-center justify-between border-b border-line-2 px-4 py-2.5">
            <span className="text-sm font-semibold">Notifications</span>
            <button onClick={() => read.mutate()} className="text-xs text-brand hover:underline">Mark all read</button>
          </div>
          <div className="max-h-96 overflow-y-auto">
            {!q.data?.items.length && <p className="px-4 py-8 text-center text-xs text-muted">Nothing yet. Agent decisions and approvals appear here.</p>}
            {q.data?.items.map((n) => (
              <button key={n.id} onClick={() => { if (n.link) nav(n.link); setOpen(false) }} className={cn('flex w-full gap-3 border-b border-line-2 px-4 py-2.5 text-left hover:bg-slate-50', !n.is_read && 'bg-brand-50/40')}>
                <span className={cn('mt-1.5 size-2 shrink-0 rounded-full', dot[n.level] ?? 'bg-brand')} />
                <span className="min-w-0"><span className="block truncate text-sm font-medium">{n.title}</span><span className="block text-xs text-ink-2 line-clamp-2">{n.body}</span><span className="text-[11px] text-muted">{date(n.created_at, true)}</span></span>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

export default function AppShell() {
  const { user, logout, can } = useAuth()
  const live = useLive()
  const info = useQuery({ queryKey: ['system-info'], queryFn: () => get<any>('/system/info'), refetchInterval: 60000 })
  const pending = useQuery({ queryKey: ['approvals', 'pending'], queryFn: () => get<Approval[]>('/approvals', { status: 'pending' }) })
  const [menu, setMenu] = useState(false)
  const visibleNav = useMemo(() => NAV.filter((n) => !n.minRole || can(n.minRole)), [can])
  return (
    <div className="flex h-full">
      <aside className="hidden w-60 shrink-0 flex-col border-r border-line bg-white lg:flex">
        <div className="flex h-14 items-center gap-2.5 border-b border-line px-4">
          <img src="/favicon.svg" alt="" className="size-8" />
          <div className="leading-tight"><div className="text-[15px] font-semibold text-ink">CX Sentinel AI</div><div className="text-[11px] text-muted">Recovery command center</div></div>
        </div>
        <nav className="flex-1 space-y-0.5 overflow-y-auto p-3">
          {visibleNav.map((n) => (
            <NavLink key={n.to} to={n.to} end={n.end} className={({ isActive }) => cn('flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm font-medium transition-colors', isActive ? 'bg-brand-50 text-brand' : 'text-ink-2 hover:bg-slate-50 hover:text-ink')}>
              <n.icon size={17} /><span className="flex-1">{n.label}</span>
              {n.badge && !!pending.data?.length && <span className="rounded-full bg-amber-100 px-1.5 text-[11px] font-semibold text-amber-800">{pending.data.length}</span>}
            </NavLink>
          ))}
        </nav>
        <div className="border-t border-line p-3 text-[11px] text-muted">
          <div className="flex items-center gap-1.5">{live.connected ? <Wifi size={13} className="text-good" /> : <WifiOff size={13} />}<span>{live.connected ? 'Live updates connected' : 'Live updates offline'}</span></div>
          {live.running && <div className="mt-1 truncate text-brand">Running: {live.running}</div>}
        </div>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 shrink-0 items-center gap-4 border-b border-line bg-white px-5">
          <div className="hidden min-w-0 md:block"><Breadcrumbs /></div>
          <div className="ml-auto flex flex-1 items-center justify-end gap-3">
            <GlobalSearch />
            <div className="hidden items-center gap-2 xl:flex">
              <Badge tone="teal">Simulated data</Badge>
              <Badge tone="neutral">Clock {info.data ? date(info.data.sim_now) : '-'}</Badge>
            </div>
            <NotificationCenter />
            <div className="relative">
              <button onClick={() => setMenu(!menu)} className="flex items-center gap-2 rounded-lg px-2 py-1 hover:bg-slate-100" aria-haspopup="menu" aria-expanded={menu}>
                <span className="grid size-8 place-items-center rounded-full bg-ink text-xs font-semibold text-white">{user?.full_name.split(' ').map((p) => p[0]).join('').slice(0, 2)}</span>
                <span className="hidden text-left leading-tight sm:block"><span className="block text-sm font-medium">{user?.full_name}</span><span className="block text-[11px] text-muted">{title(user?.role)}</span></span>
              </button>
              {menu && (
                <div role="menu" className="absolute right-0 z-40 mt-2 w-56 rounded-xl border border-line bg-white p-1.5 shadow-lg">
                  <div className="px-3 py-2 text-xs text-muted">{user?.email}</div>
                  <a href="/api/docs" target="_blank" rel="noreferrer" className="block rounded-lg px-3 py-2 text-sm hover:bg-slate-50">API documentation</a>
                  <button onClick={logout} className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-sm text-red-700 hover:bg-red-50"><LogOut size={15} />Sign out</button>
                </div>
              )}
            </div>
          </div>
        </header>
        <main className="min-h-0 flex-1 overflow-y-auto p-5 lg:p-6"><div className="mx-auto max-w-[1400px]"><Outlet /></div></main>
      </div>
      <AiAssistant />
    </div>
  )
}
