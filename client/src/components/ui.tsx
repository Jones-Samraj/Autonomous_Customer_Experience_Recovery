import { useEffect, useState, type ButtonHTMLAttributes, type ReactNode } from 'react'
import type { UseQueryResult } from '@tanstack/react-query'
import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'
import {
  AlertCircle, AlertOctagon, AlertTriangle, CheckCircle2, ChevronDown, CircleDashed, Clock, Eye, Info, Loader2, RotateCcw, ShieldCheck, X, XCircle, Inbox,
} from 'lucide-react'
import { errorMessage } from '@/lib/api'
import { title } from '@/lib/format'

export const cn = (...a: ClassValue[]) => twMerge(clsx(a))

export function Card({ title: t, subtitle, actions, children, className, pad = true }: { title?: ReactNode; subtitle?: ReactNode; actions?: ReactNode; children?: ReactNode; className?: string; pad?: boolean }) {
  return (
    <section className={cn('rounded-xl border border-line bg-surface shadow-card', className)}>
      {(t || actions) && (
        <header className="flex items-start justify-between gap-3 border-b border-line-2 px-5 py-3.5">
          <div className="min-w-0">
            <h3 className="text-[15px] font-semibold text-ink">{t}</h3>
            {subtitle && <p className="mt-0.5 text-xs text-muted">{subtitle}</p>}
          </div>
          {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
        </header>
      )}
      <div className={pad ? 'p-5' : ''}>{children}</div>
    </section>
  )
}

export function PageHeader({ title: t, description, actions }: { title: string; description?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-[22px] font-semibold text-ink">{t}</h1>
        {description && <p className="mt-1 max-w-3xl text-sm text-ink-2">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  )
}

type Tone = 'neutral' | 'blue' | 'teal' | 'green' | 'amber' | 'orange' | 'red' | 'violet'
const TONES: Record<Tone, string> = {
  neutral: 'bg-slate-100 text-slate-700 ring-slate-200',
  blue: 'bg-brand-50 text-brand-700 ring-brand-100',
  teal: 'bg-teal-50 text-teal ring-teal/20',
  green: 'bg-green-50 text-green-800 ring-green-200',
  amber: 'bg-amber-50 text-amber-800 ring-amber-200',
  orange: 'bg-orange-50 text-orange-800 ring-orange-200',
  red: 'bg-red-50 text-red-700 ring-red-200',
  violet: 'bg-violet-50 text-violet-700 ring-violet-200',
}

export function Badge({ tone = 'neutral', icon, children, className }: { tone?: Tone; icon?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <span className={cn('inline-flex items-center gap-1 whitespace-nowrap rounded-md px-2 py-0.5 text-xs font-medium ring-1 ring-inset', TONES[tone], className)}>
      {icon}
      {children}
    </span>
  )
}

export function SeverityBadge({ severity }: { severity: string }) {
  const m: Record<string, [Tone, ReactNode]> = {
    critical: ['red', <AlertOctagon key="i" size={12} />], high: ['orange', <AlertTriangle key="i" size={12} />],
    medium: ['amber', <AlertCircle key="i" size={12} />], low: ['teal', <Info key="i" size={12} />],
  }
  const [tone, icon] = m[severity] ?? ['neutral', null]
  return <Badge tone={tone} icon={icon}>{title(severity)}</Badge>
}

const STATUS: Record<string, [Tone, ReactNode]> = {
  open: ['blue', <CircleDashed key="i" size={12} />], investigating: ['blue', <Loader2 key="i" size={12} />], awaiting_approval: ['amber', <Clock key="i" size={12} />],
  pending_approval: ['amber', <Clock key="i" size={12} />], pending: ['amber', <Clock key="i" size={12} />], monitoring: ['teal', <Eye key="i" size={12} />],
  resolved: ['green', <CheckCircle2 key="i" size={12} />], recovered: ['green', <CheckCircle2 key="i" size={12} />], executed: ['green', <CheckCircle2 key="i" size={12} />],
  approved: ['blue', <ShieldCheck key="i" size={12} />], success: ['green', <CheckCircle2 key="i" size={12} />], succeeded: ['green', <CheckCircle2 key="i" size={12} />],
  reopened: ['red', <RotateCcw key="i" size={12} />], not_recovered: ['red', <XCircle key="i" size={12} />], failed: ['red', <XCircle key="i" size={12} />],
  rejected: ['neutral', <XCircle key="i" size={12} />], rolled_back: ['orange', <RotateCcw key="i" size={12} />], partial: ['amber', <AlertCircle key="i" size={12} />],
  watchlist: ['neutral', <Eye key="i" size={12} />], proposed: ['neutral', <CircleDashed key="i" size={12} />], superseded: ['neutral', <CircleDashed key="i" size={12} />],
  retrying: ['amber', <RotateCcw key="i" size={12} />], skipped: ['neutral', <CircleDashed key="i" size={12} />], running: ['blue', <Loader2 key="i" size={12} className="animate-spin" />],
  leading: ['blue', <CheckCircle2 key="i" size={12} />], plausible: ['teal', <Info key="i" size={12} />], unlikely: ['neutral', <CircleDashed key="i" size={12} />],
  refuted: ['red', <XCircle key="i" size={12} />], insufficient_data: ['amber', <AlertCircle key="i" size={12} />], insufficient: ['amber', <AlertCircle key="i" size={12} />],
  rolled: ['orange', <RotateCcw key="i" size={12} />], not_started: ['neutral', <CircleDashed key="i" size={12} />], not_applicable: ['neutral', <CircleDashed key="i" size={12} />],
  completed: ['green', <CheckCircle2 key="i" size={12} />], queued: ['neutral', <CircleDashed key="i" size={12} />],
}
export function StatusBadge({ status }: { status: string | null | undefined }) {
  const [tone, icon] = STATUS[status ?? ''] ?? ['neutral', null]
  return <Badge tone={tone} icon={icon}>{title(status)}</Badge>
}

export function KindBadge({ kind }: { kind: 'measured' | 'estimated' | string }) {
  return kind === 'measured' ? <Badge tone="green" icon={<CheckCircle2 size={12} />}>Measured</Badge> : <Badge tone="violet" icon={<Info size={12} />}>Estimated</Badge>
}

type BtnProps = ButtonHTMLAttributes<HTMLButtonElement> & { variant?: 'primary' | 'secondary' | 'ghost' | 'danger' | 'teal'; size?: 'sm' | 'md'; loading?: boolean; icon?: ReactNode }
export function Button({ variant = 'secondary', size = 'md', loading, icon, children, className, disabled, ...p }: BtnProps) {
  const v = {
    primary: 'bg-brand text-white hover:bg-brand-700 shadow-sm',
    teal: 'bg-teal text-white hover:bg-teal/90 shadow-sm',
    secondary: 'bg-white text-ink border border-line hover:bg-slate-50',
    ghost: 'text-ink-2 hover:bg-slate-100',
    danger: 'bg-white text-red-700 border border-red-200 hover:bg-red-50',
  }[variant]
  return (
    <button {...p} disabled={disabled || loading}
      className={cn('inline-flex items-center justify-center gap-1.5 rounded-lg font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50', size === 'sm' ? 'h-8 px-2.5 text-xs' : 'h-9 px-3.5 text-sm', v, className)}>
      {loading ? <Loader2 size={14} className="animate-spin" /> : icon}
      {children}
    </button>
  )
}

export function Stat({
  label,
  value,
  hint,
  icon,
  tone = 'blue',
  onClick,
}: {
  label: string
  value: ReactNode
  hint?: ReactNode
  icon?: ReactNode
  tone?: Tone
  onClick?: () => void
}) {
  const isClickable = !!onClick
  return (
    <div
      role={isClickable ? 'button' : undefined}
      tabIndex={isClickable ? 0 : undefined}
      onClick={onClick}
      onKeyDown={(e) => {
        if (isClickable && (e.key === 'Enter' || e.key === ' ')) {
          e.preventDefault()
          onClick()
        }
      }}
      className={cn(
        'group rounded-xl border border-line bg-surface p-4 shadow-card transition-all duration-200',
        isClickable &&
          'cursor-pointer hover:-translate-y-0.5 hover:border-brand/40 hover:shadow-md focus:outline-none focus:ring-2 focus:ring-brand/20 select-none'
      )}
    >
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium uppercase tracking-wide text-muted transition-colors group-hover:text-ink">
          {label}
        </span>
        {icon && (
          <span className={cn('grid size-7 place-items-center rounded-md transition-transform group-hover:scale-105', TONES[tone])}>
            {icon}
          </span>
        )}
      </div>
      <div className="mt-2 text-[26px] font-semibold leading-none text-ink">{value}</div>
      {hint && <div className="mt-2 text-xs text-ink-2">{hint}</div>}
      {isClickable && (
        <div className="mt-2.5 flex items-center justify-between border-t border-line-2 pt-2 text-[11px] font-medium text-brand transition-colors group-hover:underline">
          <span>Inspect source & details</span>
          <span>&rarr;</span>
        </div>
      )}
    </div>
  )
}

export function Spinner({ label = 'Loading' }: { label?: string }) {
  return <div role="status" className="flex items-center gap-2 py-10 text-sm text-muted justify-center"><Loader2 size={16} className="animate-spin" />{label}...</div>
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn('animate-pulse rounded-md bg-slate-100', className)} />
}

export function ErrorState({ error, retry }: { error: unknown; retry?: () => void }) {
  return (
    <div role="alert" className="flex flex-col items-center gap-2 rounded-lg border border-red-200 bg-red-50 px-4 py-8 text-center">
      <XCircle className="text-red-600" size={22} />
      <p className="text-sm font-medium text-red-800">Something went wrong</p>
      <p className="max-w-md text-xs text-red-700">{errorMessage(error)}</p>
      {retry && <Button size="sm" onClick={retry}>Retry</Button>}
    </div>
  )
}

export function EmptyState({ title: t, hint, action, icon }: { title: string; hint?: ReactNode; action?: ReactNode; icon?: ReactNode }) {
  return (
    <div className="flex flex-col items-center gap-2 px-4 py-12 text-center">
      <span className="grid size-10 place-items-center rounded-full bg-slate-100 text-muted">{icon ?? <Inbox size={18} />}</span>
      <p className="text-sm font-medium text-ink">{t}</p>
      {hint && <p className="max-w-sm text-xs text-muted">{hint}</p>}
      {action}
    </div>
  )
}

/** Renders loading / error states for a query, then the children with data. */
export function Async<T>({ q, children, skeleton }: { q: UseQueryResult<T>; children: (data: T) => ReactNode; skeleton?: ReactNode }) {
  if (q.isLoading) return <>{skeleton ?? <Spinner />}</>
  if (q.isError) return <ErrorState error={q.error} retry={() => q.refetch()} />
  if (q.data === undefined) return null
  return <>{children(q.data)}</>
}

export function Tabs<T extends string>({ tabs, value, onChange }: { tabs: { id: T; label: string; count?: number }[]; value: T; onChange: (v: T) => void }) {
  return (
    <div role="tablist" className="mb-4 flex gap-1 overflow-x-auto border-b border-line">
      {tabs.map((t) => (
        <button key={t.id} role="tab" aria-selected={value === t.id} onClick={() => onChange(t.id)}
          className={cn('-mb-px whitespace-nowrap border-b-2 px-3.5 py-2 text-sm font-medium transition-colors', value === t.id ? 'border-brand text-brand' : 'border-transparent text-ink-2 hover:text-ink')}>
          {t.label}{t.count != null && <span className="ml-1.5 rounded-full bg-slate-100 px-1.5 py-0.5 text-[11px] text-ink-2">{t.count}</span>}
        </button>
      ))}
    </div>
  )
}

export function Table({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cn('overflow-x-auto', className)}><table className="w-full text-sm">{children}</table></div>
}
export const Th = ({ children, className }: { children?: ReactNode; className?: string }) => (
  <th className={cn('whitespace-nowrap border-b border-line bg-slate-50/70 px-3 py-2 text-left text-[11px] font-semibold uppercase tracking-wide text-muted', className)}>{children}</th>
)
export const Td = ({ children, className, colSpan }: { children?: ReactNode; className?: string; colSpan?: number }) => (
  <td colSpan={colSpan} className={cn('border-b border-line-2 px-3 py-2.5 align-middle text-ink', className)}>{children}</td>
)

export function Meter({ value, tone = 'blue', label, className }: { value: number; tone?: 'blue' | 'teal' | 'red' | 'amber' | 'green'; label?: string; className?: string }) {
  const c = { blue: 'bg-brand', teal: 'bg-teal', red: 'bg-critical', amber: 'bg-warning', green: 'bg-good' }[tone]
  const v = Math.max(0, Math.min(1, value))
  return (
    <div className={cn('flex items-center gap-2', className)} title={label}>
      <div className="h-1.5 w-full min-w-16 overflow-hidden rounded-full bg-slate-100"><div className={cn('h-full rounded-full', c)} style={{ width: `${v * 100}%` }} /></div>
      <span className="tnum w-9 shrink-0 text-right text-xs text-ink-2">{Math.round(v * 100)}%</span>
    </div>
  )
}

export function Disclosure({ summary, children, defaultOpen = false }: { summary: ReactNode; children: ReactNode; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div>
      <button onClick={() => setOpen(!open)} aria-expanded={open} className="flex w-full items-center justify-between gap-2 text-left">
        <span className="min-w-0 flex-1">{summary}</span>
        <ChevronDown size={16} className={cn('shrink-0 text-muted transition-transform', open && 'rotate-180')} />
      </button>
      {open && <div className="mt-2">{children}</div>}
    </div>
  )
}

export function Drawer({ open, onClose, title: t, children, width = 'max-w-2xl' }: { open: boolean; onClose: () => void; title: ReactNode; children: ReactNode; width?: string }) {
  useEffect(() => {
    if (!open) return
    const h = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', h)
    return () => window.removeEventListener('keydown', h)
  }, [open, onClose])
  if (!open) return null
  return (
    <div className="fixed inset-0 z-50 flex justify-end" role="dialog" aria-modal="true">
      <div className="absolute inset-0 bg-ink/30" onClick={onClose} />
      <aside className={cn('relative flex h-full w-full flex-col bg-white shadow-xl', width)}>
        <header className="flex items-center justify-between border-b border-line px-5 py-3.5">
          <h2 className="text-base font-semibold">{t}</h2>
          <button onClick={onClose} aria-label="Close" className="rounded-md p-1 text-muted hover:bg-slate-100"><X size={18} /></button>
        </header>
        <div className="flex-1 overflow-y-auto p-5">{children}</div>
      </aside>
    </div>
  )
}

export const inputCls = 'h-9 w-full rounded-lg border border-line bg-white px-3 text-sm text-ink placeholder:text-muted focus:border-brand focus:outline-none focus:ring-2 focus:ring-brand/20'
export function Field({ label, children, hint }: { label: string; children: ReactNode; hint?: string }) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium text-ink-2">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-[11px] text-muted">{hint}</span>}
    </label>
  )
}

export function KV({ k, v }: { k: string; v: ReactNode }) {
  return <div className="flex items-start justify-between gap-4 py-1.5 text-sm"><dt className="text-ink-2">{k}</dt><dd className="text-right font-medium text-ink">{v}</dd></div>
}

export function Banner({ tone = 'blue', children, icon }: { tone?: Tone; children: ReactNode; icon?: ReactNode }) {
  return <div className={cn('flex items-start gap-2 rounded-lg px-3 py-2.5 text-sm ring-1 ring-inset', TONES[tone])}>{icon ?? <Info size={16} className="mt-0.5 shrink-0" />}<div>{children}</div></div>
}
