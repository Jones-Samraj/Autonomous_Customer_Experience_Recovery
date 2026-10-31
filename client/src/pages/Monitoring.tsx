import { Fragment, useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, FastForward } from 'lucide-react'
import { get, post } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import { date, pct, shortDay, title } from '@/lib/format'
import type { Issue, KpiSeries } from '@/lib/types'
import { Async, Badge, Banner, Button, Card, EmptyState, Field, inputCls, PageHeader, StatusBadge, Table, Td, Th, cn } from '@/components/ui'
import { BarsChart, ChartCard, TrendChart } from '@/components/charts'
import { ActivityTimeline } from '@/components/AgentTimeline'
import { toast } from '@/components/toast'

interface Mon { sim_now: string; kpis: KpiSeries[]; interventions: any[]; reopened_investigations: Issue[]; timeline: any[]; world_connected: boolean }

export default function Monitoring() {
  const { can } = useAuth()
  const qc = useQueryClient()
  const [kpi, setKpi] = useState('delivery_success_rate')
  const [days, setDays] = useState(7)
  const [open, setOpen] = useState<number | null>(null)
  const q = useQuery({ queryKey: ['monitoring'], queryFn: () => get<Mon>('/monitoring/overview') })
  const adv = useMutation({
    mutationFn: () => post('/monitoring/advance', { days }),
    onSuccess: (r: any) => {
      toast.success(r.reopened?.length ? `Clock advanced ${days} days. An intervention failed verification and the investigation was re-opened.` : `Clock advanced ${days} days; ${r.verified.length} issue(s) verified.`)
      qc.invalidateQueries()
    },
    onError: toast.error,
  })
  return (
    <>
      <PageHeader title="Recovery Monitoring" description="Executing an action is not recovery. The Verification agent compares KPIs of cohorts that started after the intervention against the pre-intervention cohort, and re-opens the investigation when the fix does not work."
        actions={can('analyst') && (
          <div className="flex items-end gap-2"><Field label="Simulated time"><select className={`${inputCls} w-32`} value={days} onChange={(e) => setDays(Number(e.target.value))}>{[3, 7, 14].map((d) => <option key={d} value={d}>+{d} days</option>)}</select></Field>
            <Button variant="primary" icon={<FastForward size={15} />} loading={adv.isPending} onClick={() => adv.mutate()}>Advance &amp; verify</Button></div>)} />
      <Async q={q}>
        {(m) => {
          const sel = m.kpis.find((k) => k.code === kpi) ?? m.kpis[0]
          const exec = m.interventions.filter((i) => i.executed_at).map((i) => ({ x: i.executed_at.slice(0, 10), label: i.code, color: '#6250d6' }))
          const dates = new Set(sel?.series.map((p) => p.date))
          const markers = exec.filter((e) => dates.has(e.x))
          const rootFix = m.interventions.filter((i) => i.role === 'root_cause_fix')
          const cmp = rootFix.filter((i) => i.verification?.pre?.rate != null && i.verification?.post?.rate != null).map((i) => ({ name: i.code, before: Number((i.verification.pre.rate * 100).toFixed(1)), after: Number((i.verification.post.rate * 100).toFixed(1)) }))
          return (
            <div className="space-y-5">
              {!m.world_connected && <Banner tone="amber">No simulated enterprise is connected, so the clock cannot be advanced. Load the sample datasets first.</Banner>}
              <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5">
                {m.kpis.map((k) => {
                  const better = k.latest != null && k.baseline != null ? (k.direction === 'higher_better' ? k.latest >= k.baseline : k.latest <= k.baseline) : null
                  return (
                    <button key={k.code} onClick={() => setKpi(k.code)} className={cn('rounded-xl border bg-white p-3 text-left shadow-card transition-colors', sel?.code === k.code ? 'border-brand ring-2 ring-brand/15' : 'border-line hover:border-slate-300')}>
                      <div className="text-xs font-medium text-muted">{k.name}</div>
                      <div className="tnum mt-1 text-xl font-semibold">{k.latest == null ? '-' : k.latest.toFixed(k.unit === '%' ? 1 : 2)}<span className="ml-1 text-xs font-normal text-muted">{k.unit}</span></div>
                      <div className="mt-1 flex items-center gap-1.5 text-[11px] text-ink-2">baseline {k.baseline?.toFixed(1) ?? '-'} {better != null && <Badge tone={better ? 'green' : 'red'}>{better ? 'on baseline' : 'off baseline'}</Badge>}</div>
                    </button>
                  )
                })}
              </div>
              {sel && (
                <ChartCard title={sel.name} subtitle={`${sel.unit} per day · dashed line = 14-day baseline · purple markers = executed interventions`} table={{ headers: ['Date', sel.name], rows: sel.series.map((p) => [p.date, p.value.toFixed(2)]) }}>
                  <TrendChart data={sel.series} xFmt={shortDay} yFmt={(v) => v.toFixed(sel.unit === '%' ? 0 : 1)} series={[{ key: 'value', label: sel.name }]} baseline={sel.baseline} markers={markers} height={260} />
                </ChartCard>
              )}
              <div className="grid gap-5 xl:grid-cols-3">
                <Card title="Intervention verification" subtitle="Pre- vs post-intervention comparison of the issue KPI" className="xl:col-span-2" pad={false}>
                  {!m.interventions.length ? <EmptyState title="Nothing executed yet" hint="Approve an intervention in the Approval Center, then advance the simulated clock." /> : (
                    <Table>
                      <thead><tr><Th>Intervention</Th><Th>Issue</Th><Th>Executed</Th><Th>Pre</Th><Th>Post</Th><Th>Verdict</Th></tr></thead>
                      <tbody>
                        {m.interventions.map((i) => (
                          <Fragment key={i.id}>
                            <tr className="cursor-pointer hover:bg-slate-50" onClick={() => setOpen(open === i.id ? null : i.id)}>
                              <Td className="max-w-xs"><div className="font-medium">{i.title}</div><div className="text-[11px] text-muted">{i.code} · {title(i.role)}</div></Td>
                              <Td><Link to={`/investigations/${i.issue.id}`} className="text-brand hover:underline" onClick={(e) => e.stopPropagation()}>{i.issue.code}</Link></Td>
                              <Td className="whitespace-nowrap text-xs">{date(i.executed_at)}</Td>
                              <Td className="tnum">{i.verification?.pre?.rate != null ? pct(i.verification.pre.rate, 1) : '-'}</Td>
                              <Td className="tnum">{i.verification?.post?.rate != null ? pct(i.verification.post.rate, 1) : '-'}</Td>
                              <Td>{i.role === 'root_cause_fix' ? <StatusBadge status={i.verification?.verdict ?? i.verification_status} /> : <StatusBadge status="not_applicable" />}</Td>
                            </tr>
                            {open === i.id && (
                              <tr><Td colSpan={6} className="bg-slate-50">
                                <p className="text-[13px] text-ink-2">{i.verification?.explanation ?? 'Verification is pending: advance the simulated clock to collect post-intervention evidence.'}</p>
                                {i.verification?.secondary_kpis && <div className="mt-3 flex flex-wrap gap-2">{Object.entries(i.verification.secondary_kpis).map(([k, v]: any) => <Badge key={k} tone={v.improved ? 'green' : 'amber'}>{title(k)}: {v.pre.toFixed(1)} → {v.post.toFixed(1)}</Badge>)}</div>}
                                {i.verification?.control && <p className="mt-2 text-xs text-muted">Control check - targeted units: {pct(i.verification.control.targeted_pre, 1)} → {pct(i.verification.control.targeted_post, 1)}; all other units: {pct(i.verification.control.other_pre, 1)} → {pct(i.verification.control.other_post, 1)}.</p>}
                              </Td></tr>
                            )}
                          </Fragment>
                        ))}
                      </tbody>
                    </Table>
                  )}
                </Card>
                <ChartCard title="Before vs after" subtitle="Issue KPI failure rate (%) around the intervention" table={{ headers: ['Intervention', 'Before %', 'After %'], rows: cmp.map((c) => [c.name, c.before, c.after]) }}>
                  {cmp.length ? <BarsChart data={cmp} xKey="name" height={230} series={[{ key: 'before', label: 'Before', color: '#898781' }, { key: 'after', label: 'After', color: '#2a78d6' }]} yFmt={(v) => `${v}%`} /> : <EmptyState title="No verified comparison yet" />}
                </ChartCard>
              </div>
              <div className="grid gap-5 xl:grid-cols-2">
                <Card title="Re-opened investigations" subtitle="Failed interventions send the case back to root-cause analysis">
                  {!m.reopened_investigations.length ? <EmptyState title="None" hint="Investigations re-open automatically when verification fails." icon={<AlertTriangle size={18} />} /> : (
                    <ul className="space-y-2">{m.reopened_investigations.map((i) => <li key={i.id} className="flex items-center justify-between rounded-lg border border-line p-3"><div><Link to={`/investigations/${i.id}`} className="font-medium text-brand hover:underline">{i.code}</Link><p className="text-xs text-ink-2">{i.title}</p></div><div className="text-right"><StatusBadge status={i.status} /><p className="mt-1 text-[11px] text-muted">re-opened ×{i.reopen_count} · iteration {i.iteration}</p></div></li>)}</ul>
                  )}
                </Card>
                <Card title="Recovery timeline" subtitle="Executions and verification outcomes"><ActivityTimeline items={m.timeline} /></Card>
              </div>
            </div>
          )
        }}
      </Async>
    </>
  )
}
