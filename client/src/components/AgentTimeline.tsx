import { Fragment, useState } from 'react'
import { Bot, FlaskConical, ShieldCheck, Wrench, GitBranch } from 'lucide-react'
import { date } from '@/lib/format'
import type { AgentRun, TimelineItem } from '@/lib/types'
import { Badge, StatusBadge, Table, Td, Th, cn } from './ui'

const ICON: Record<string, any> = { agent: Bot, approval: ShieldCheck, scenario: FlaskConical, executed: Wrench, onset: GitBranch }

export function ActivityTimeline({ items }: { items: TimelineItem[] }) {
  const rows = [...items].reverse()
  if (!rows.length) return <p className="py-8 text-center text-sm text-muted">No activity recorded yet.</p>
  return (
    <ol className="relative ml-3 space-y-4 border-l border-line pl-6">
      {rows.slice(0, 80).map((t, i) => {
        const Icon = ICON[t.kind] ?? Bot
        return (
          <li key={i} className="relative">
            <span className={cn('absolute -left-[37px] grid size-6 place-items-center rounded-full border bg-white', t.status === 'failed' ? 'border-critical text-critical' : 'border-line text-brand')}><Icon size={13} /></span>
            <div className="flex flex-wrap items-center gap-2"><span className="text-sm font-medium">{t.title}</span>{t.status && <StatusBadge status={t.status} />}<span className="text-xs text-muted">{date(t.at, true)}</span></div>
            {t.detail && <p className="mt-0.5 max-w-3xl text-[13px] text-ink-2 line-clamp-3">{t.detail}</p>}
          </li>
        )
      })}
    </ol>
  )
}

export function AgentRunsTable({ runs, showIssue }: { runs: AgentRun[]; showIssue?: boolean }) {
  const [open, setOpen] = useState<number | null>(null)
  return (
    <Table>
      <thead><tr><Th>When</Th>{showIssue && <Th>Issue</Th>}<Th>Agent</Th><Th>Task performed</Th><Th>Reasoning summary</Th><Th>Status</Th><Th>Time</Th></tr></thead>
      <tbody>
        {runs.map((r) => (
          <Fragment key={r.id}>
            <tr className="cursor-pointer align-top hover:bg-slate-50" onClick={() => setOpen(open === r.id ? null : r.id)}>
              <Td className="whitespace-nowrap text-xs text-ink-2">{date(r.started_at, true)}</Td>
              {showIssue && <Td>{r.issue_code ?? '-'}</Td>}
              <Td className="whitespace-nowrap font-medium">{r.agent}{r.attempt > 1 && <Badge tone="amber" className="ml-1">attempt {r.attempt}</Badge>}</Td>
              <Td className="max-w-[220px] text-ink-2">{r.task}</Td>
              <Td className="max-w-xl text-[13px] text-ink-2"><div className={open === r.id ? '' : 'line-clamp-2'}>{r.reasoning_summary ?? r.error}</div></Td>
              <Td><StatusBadge status={r.status} /></Td>
              <Td className="tnum whitespace-nowrap text-xs text-ink-2">{r.duration_ms == null ? '-' : `${r.duration_ms} ms`}</Td>
            </tr>
            {open === r.id && (
              <tr><Td colSpan={showIssue ? 7 : 6} className="bg-slate-50">
                <div className="grid gap-3 md:grid-cols-2">
                  <div><p className="mb-1 text-xs font-semibold text-muted">Input evidence</p><pre className="max-h-56 overflow-auto rounded-lg bg-white p-3 text-[11px] ring-1 ring-line">{JSON.stringify(r.input_summary, null, 2)}</pre></div>
                  <div><p className="mb-1 text-xs font-semibold text-muted">Output</p><pre className="max-h-56 overflow-auto rounded-lg bg-white p-3 text-[11px] ring-1 ring-line">{JSON.stringify(r.output_summary, null, 2)}</pre></div>
                </div>
                {r.error && <p className="mt-2 text-xs text-red-700">Error: {r.error}</p>}
                <p className="mt-2 text-[11px] text-muted">Run {r.run_id}. Decisions are explained with concise, evidence-grounded summaries - hidden reasoning is never exposed.</p>
              </Td></tr>
            )}
          </Fragment>
        ))}
      </tbody>
    </Table>
  )
}
