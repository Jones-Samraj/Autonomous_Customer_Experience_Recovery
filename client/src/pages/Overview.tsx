import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertOctagon, CheckCheck, Coins, Play, ShieldCheck, Users, Radar, Microscope } from 'lucide-react'
import { get, post } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import { date, inr, num, pct, shortDay } from '@/lib/format'
import type { Approval, Issue, KpiSeries } from '@/lib/types'
import { Async, Button, Card, EmptyState, SeverityBadge, Stat, StatusBadge, Table, Td, Th } from '@/components/ui'
import { BarsChart, ChartCard, SEVERITY_COLOR, TrendChart, toTable } from '@/components/charts'
import { toast } from '@/components/toast'

interface Overview {
  sim_now: string
  kpis: { total_issues: number; critical_issues: number; watchlist: number; affected_customers: number; revenue_at_risk: number; active_investigations: number; pending_approvals: number; recovery_success_rate: number | null; verified_outcomes: number }
  issues_by_severity: { severity: string; count: number }[]
  revenue_by_issue: { issue: string; title: string; revenue_at_risk: number; affected: number; severity: string }[]
  recent_incidents: Issue[]
  trends: KpiSeries[]
}

function merge(trends: KpiSeries[], codes: string[]) {
  const by: Record<string, any> = {}
  trends.filter((t) => codes.includes(t.code)).forEach((t) => t.series.forEach((p) => { (by[p.date] ??= { date: p.date })[t.code] = Number(p.value.toFixed(2)) }))
  return Object.values(by).sort((a, b) => a.date.localeCompare(b.date))
}

export default function Overview() {
  const { can } = useAuth()
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['overview'], queryFn: () => get<Overview>('/dashboard/overview') })
  const pend = useQuery({ queryKey: ['approvals', 'pending'], queryFn: () => get<Approval[]>('/approvals', { status: 'pending' }) })
  const run = useMutation({
    mutationFn: () => post('/pipeline/run'),
    onSuccess: () => { toast.info('Full analysis started: agents are detecting, investigating and planning. Progress appears live.'); setTimeout(() => qc.invalidateQueries(), 4000) },
    onError: toast.error,
  })
  return (
    <>
      <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-[22px] font-semibold">Executive Overview</h1>
          <p className="mt-1 text-sm text-ink-2">Every figure is computed from ingested evidence. As of simulated clock {q.data ? date(q.data.sim_now) : '...'}.</p>
        </div>
        {can('analyst') && <Button variant="primary" icon={<Play size={15} />} loading={run.isPending} onClick={() => run.mutate()}>Run full analysis</Button>}
      </div>
      <Async q={q}>
        {(o) => {
          const k = o.kpis
          if (!k.total_issues && !o.recent_incidents.length) return (
            <Card><EmptyState title="No issues detected yet" hint="Load the sample datasets in the Signal Explorer, then run the full analysis to detect and investigate emerging problems."
              action={<Link to="/signals"><Button variant="primary">Open Signal Explorer</Button></Link>} /></Card>)
          return (
            <div className="space-y-5">
              <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-7">
                <Stat label="Detected issues" value={k.total_issues} hint={k.watchlist ? `${k.watchlist} on watchlist` : 'none on watchlist'} icon={<Radar size={15} />} />
                <Stat label="Critical" value={k.critical_issues} tone="red" icon={<AlertOctagon size={15} />} hint="severity score ≥ 75" />
                <Stat label="Affected customers" value={num(k.affected_customers)} tone="teal" icon={<Users size={15} />} hint="measured, open issues" />
                <Stat label="Revenue at risk" value={inr(k.revenue_at_risk)} tone="amber" icon={<Coins size={15} />} hint="estimated, 3-month horizon" />
                <Stat label="Active investigations" value={k.active_investigations} icon={<Microscope size={15} />} />
                <Stat label="Pending approvals" value={k.pending_approvals} tone="amber" icon={<ShieldCheck size={15} />} hint={<Link to="/approvals" className="text-brand hover:underline">Review now</Link>} />
                <Stat label="Recovery success" value={k.recovery_success_rate == null ? 'n/a' : pct(k.recovery_success_rate)} tone="green" icon={<CheckCheck size={15} />}
                  hint={k.verified_outcomes ? `${k.verified_outcomes} verified outcome(s)` : 'no verified outcomes yet'} />
              </div>
              <div className="grid gap-5 xl:grid-cols-3">
                <ChartCard title="Complaint volume" subtitle="Negative customer-voice signals per day" className="xl:col-span-2"
                  table={toTable(merge(o.trends, ['complaint_volume']), 'date', [{ key: 'complaint_volume', label: 'Complaints' }])}>
                  <TrendChart data={merge(o.trends, ['complaint_volume'])} xFmt={shortDay} series={[{ key: 'complaint_volume', label: 'Complaints per day' }]}
                    baseline={o.trends.find((t) => t.code === 'complaint_volume')?.baseline} baselineLabel="14-day baseline" />
                </ChartCard>
                <ChartCard title="Issues by severity" subtitle="Confirmed issues" table={{ headers: ['Severity', 'Issues'], rows: o.issues_by_severity.map((s) => [s.severity, s.count]) }}>
                  <BarsChart data={o.issues_by_severity} xKey="severity" series={[{ key: 'count', label: 'Issues' }]} height={220} colorByRow={(r) => SEVERITY_COLOR[r.severity]} />
                </ChartCard>
              </div>
              <div className="grid gap-5 xl:grid-cols-3">
                <ChartCard title="Service success rates" subtitle="Daily share of successful outcomes (%)" className="xl:col-span-2"
                  table={toTable(merge(o.trends, ['delivery_success_rate', 'payment_success_rate', 'refund_completion_rate', 'service_availability']), 'date', [
                    { key: 'delivery_success_rate', label: 'Delivery on time' }, { key: 'payment_success_rate', label: 'Payment success' }, { key: 'refund_completion_rate', label: 'Refund in SLA' }, { key: 'service_availability', label: 'Crash-free sessions' }])}>
                  <TrendChart data={merge(o.trends, ['delivery_success_rate', 'payment_success_rate', 'refund_completion_rate', 'service_availability'])} xFmt={shortDay} yFmt={(v) => `${v.toFixed(0)}%`} domain={[60, 100]}
                    series={[{ key: 'delivery_success_rate', label: 'Delivery on time' }, { key: 'payment_success_rate', label: 'Payment success' }, { key: 'refund_completion_rate', label: 'Refund in SLA' }, { key: 'service_availability', label: 'Crash-free sessions' }]} />
                </ChartCard>
                <ChartCard title="Revenue at risk by issue" subtitle="Estimated, INR (3-month horizon)" table={{ headers: ['Issue', 'Revenue at risk', 'Affected'], rows: o.revenue_by_issue.map((r) => [r.title, inr(r.revenue_at_risk), num(r.affected)]) }}>
                  <BarsChart layout="vertical" data={o.revenue_by_issue} xKey="title" series={[{ key: 'revenue_at_risk', label: 'Revenue at risk' }]} height={220} yFmt={(v) => inr(v)} colorByRow={(r) => SEVERITY_COLOR[r.severity]} labelWidth={120} />
                </ChartCard>
              </div>
              <div className="grid gap-5 xl:grid-cols-3">
                <Card title="Recent incidents" subtitle="Most recently updated issues" className="xl:col-span-2" pad={false}>
                  <Table>
                    <thead><tr><Th>Issue</Th><Th>Severity</Th><Th>Status</Th><Th>Confidence</Th><Th>Growth</Th><Th>Onset</Th></tr></thead>
                    <tbody>
                      {o.recent_incidents.map((i) => (
                        <tr key={i.id} className="hover:bg-slate-50">
                          <Td><Link to={`/investigations/${i.id}`} className="font-medium text-brand hover:underline">{i.code}</Link><div className="max-w-md truncate text-xs text-ink-2">{i.title}</div></Td>
                          <Td><SeverityBadge severity={i.severity} /></Td><Td><StatusBadge status={i.status} /></Td>
                          <Td className="tnum">{pct(i.detection_confidence)}</Td><Td className="tnum">{i.growth_rate >= 0 ? '+' : ''}{pct(i.growth_rate)}</Td><Td>{date(i.onset_at)}</Td>
                        </tr>
                      ))}
                    </tbody>
                  </Table>
                </Card>
                <Card title="Awaiting your decision" subtitle="Consequential actions need human approval" actions={<Link to="/approvals" className="text-xs text-brand hover:underline">All approvals</Link>}>
                  {!pend.data?.length ? <EmptyState title="Nothing pending" hint="Approval requests appear here when agents recommend a consequential action." icon={<ShieldCheck size={18} />} /> : (
                    <ul className="space-y-3">
                      {pend.data.slice(0, 4).map((a) => (
                        <li key={a.id} className="rounded-lg border border-line p-3">
                          <div className="flex items-center justify-between gap-2"><span className="text-xs font-medium text-muted">{a.issue?.code} · {a.intervention.code}</span><StatusBadge status="pending" /></div>
                          <p className="mt-1 text-sm font-medium">{a.intervention.title}</p>
                          <p className="mt-0.5 text-xs text-ink-2">Cost {inr(a.intervention.cost_inr)} · expected impact {pct(a.intervention.expected_impact)}</p>
                        </li>
                      ))}
                    </ul>
                  )}
                </Card>
              </div>
            </div>
          )
        }}
      </Async>
    </>
  )
}
