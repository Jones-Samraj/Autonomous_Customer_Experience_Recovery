import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Award, Send } from 'lucide-react'
import { get, post } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import { CRITERIA_LABEL, inr, num, pct, title } from '@/lib/format'
import type { Intervention, Issue } from '@/lib/types'
import { Async, Badge, Banner, Button, Card, Drawer, EmptyState, Field, inputCls, Meter, PageHeader, SeverityBadge, StatusBadge, Table, Td, Th } from '@/components/ui'
import { BarsChart, ChartCard } from '@/components/charts'
import { toast } from '@/components/toast'

const ROLE_LABEL: Record<string, string> = { root_cause_fix: 'Root-cause actions', customer_mitigation: 'Customer mitigation', coordination: 'Coordination' }
const CRIT_COLOR: Record<string, string> = { expected_impact: '#2a78d6', customer_benefit: '#1baf7a', confidence: '#6250d6', feasibility: '#eda100', reversibility: '#e87ba4', business_risk: '#e34948', cost: '#eb6834', execution_time: '#898781' }

function IvDetail({ id }: { id: number }) {
  const q = useQuery({ queryKey: ['intervention', id], queryFn: () => get<Intervention>(`/interventions/${id}`) })
  return (
    <Async q={q}>
      {(iv) => (
        <div className="space-y-4 text-sm">
          <div className="flex flex-wrap gap-2"><StatusBadge status={iv.status} /><Badge tone="neutral">{ROLE_LABEL[iv.role]}</Badge>{iv.is_recommended && <Badge tone="blue" icon={<Award size={11} />}>Recommended</Badge>}{iv.is_consequential && <Badge tone="amber">Consequential: needs approval</Badge>}</div>
          <p className="rounded-lg bg-slate-50 p-3 text-ink-2">{iv.rationale}</p>
          {iv.criteria && <div><p className="mb-1 text-xs font-semibold text-muted">Weighted contribution to utility ({iv.utility.toFixed(3)})</p>
            <ul className="space-y-1">{Object.entries(iv.criteria.weighted_contribution).map(([k, v]) => <li key={k} className="flex items-center justify-between text-xs"><span>{CRITERIA_LABEL[k]}</span><span className={`tnum font-medium ${v < 0 ? 'text-critical' : 'text-ink'}`}>{v >= 0 ? '+' : ''}{v.toFixed(3)}</span></li>)}</ul></div>}
          {iv.target_hypothesis && <div><p className="mb-1 text-xs font-semibold text-muted">Addresses hypothesis</p><p className="font-medium">{iv.target_hypothesis.title} <span className="text-ink-2">({pct(iv.target_hypothesis.confidence)} confidence)</span></p></div>}
          {iv.execution_logs && iv.execution_logs.length > 0 && <div><p className="mb-1 text-xs font-semibold text-muted">Execution log</p>
            <ul className="space-y-1.5">{iv.execution_logs.map((l) => <li key={l.id} className="rounded-lg border border-line-2 p-2 text-xs"><div className="flex items-center justify-between"><span className="font-medium">{l.action} <span className="text-muted">→ {l.system}</span></span><StatusBadge status={l.status} /></div><div className="mt-0.5 text-muted">attempt {l.attempt} · {l.duration_ms} ms · key {l.idempotency_key}</div>{l.error && <div className="text-red-700">{l.error}</div>}</li>)}</ul></div>}
          {iv.tickets && iv.tickets.length > 0 && <div><p className="mb-1 text-xs font-semibold text-muted">Enterprise records created</p><ul className="text-xs">{iv.tickets.map((t: any) => <li key={t.id}>{t.ticket_no} · {title(t.kind)} · {t.department} · {t.status}</li>)}</ul></div>}
        </div>
      )}
    </Async>
  )
}

export default function Interventions() {
  const { can } = useAuth()
  const qc = useQueryClient()
  const [issueId, setIssueId] = useState<number | null>(null)
  const [open, setOpen] = useState<number | null>(null)
  const issues = useQuery({ queryKey: ['issues'], queryFn: () => get<Issue[]>('/issues') })
  const sel = issueId ?? issues.data?.find((i) => i.status !== 'watchlist')?.id ?? null
  const ivs = useQuery({ queryKey: ['interventions', sel], queryFn: () => get<Intervention[]>('/interventions', { issue_id: sel }), enabled: sel != null })
  const submit = useMutation({ mutationFn: (id: number) => post(`/interventions/${id}/submit`), onSuccess: () => { toast.success('Submitted for human approval'); qc.invalidateQueries() }, onError: toast.error })
  const issue = issues.data?.find((i) => i.id === sel)
  return (
    <>
      <PageHeader title="Intervention Center" description="Alternative recovery strategies scored on expected impact, cost, time, customer benefit, risk, feasibility, confidence and reversibility. Consequential actions are never executed without approval."
        actions={issues.data && <Field label="Issue"><select className={`${inputCls} w-72`} value={sel ?? ''} onChange={(e) => setIssueId(Number(e.target.value))}>{issues.data.filter((i) => i.status !== 'watchlist').map((i) => <option key={i.id} value={i.id}>{i.code} · {i.category}</option>)}</select></Field>} />
      {issue && <div className="mb-4 flex items-center gap-2 text-sm text-ink-2"><SeverityBadge severity={issue.severity} /><span>{issue.title}</span><StatusBadge status={issue.status} />{issue.top_hypothesis && <span>· leading cause: <b className="text-ink">{issue.top_hypothesis.title}</b> ({pct(issue.top_hypothesis.confidence)})</span>}</div>}
      <Async q={ivs}>
        {(list) => {
          if (!list.length) return <Card><EmptyState title="No interventions planned" hint="Run the investigation to generate ranked strategies." /></Card>
          const cur = list.filter((i) => i.iteration === Math.max(...list.map((x) => x.iteration)) || i.status === 'executed')
          const fixes = cur.filter((i) => i.role === 'root_cause_fix')
          const pkg = cur.filter((i) => i.is_recommended)
          const chart = fixes.map((f) => ({ name: f.title.length > 38 ? f.title.slice(0, 36) + '…' : f.title, ...Object.fromEntries(Object.entries(f.criteria?.weighted_contribution ?? {}).map(([k, v]) => [k, Number(v.toFixed(3))])) }))
          return (
            <div className="space-y-5">
              <Card title="Recommended coordinated package" subtitle="A root-cause action, a customer mitigation and an owned incident - planned together">
                <div className="grid gap-3 md:grid-cols-3">
                  {pkg.map((iv) => (
                    <div key={iv.id} className="rounded-xl border border-brand/25 bg-brand-50/40 p-4">
                      <div className="flex items-center justify-between"><Badge tone="blue">{ROLE_LABEL[iv.role]}</Badge><StatusBadge status={iv.status} /></div>
                      <h4 className="mt-2 text-sm font-semibold">{iv.title}</h4>
                      <p className="mt-1 text-xs text-ink-2 line-clamp-4">{iv.rationale}</p>
                      <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-ink-2"><span>Cost <b className="text-ink">{inr(iv.cost_inr)}</b></span><span>Impact <b className="text-ink">{pct(iv.expected_impact)}</b></span><span>Time <b className="text-ink">{iv.execution_hours}h</b></span></div>
                      <button onClick={() => setOpen(iv.id)} className="mt-2 text-xs font-medium text-brand hover:underline">Why this ranking?</button>
                    </div>
                  ))}
                </div>
                {pkg.some((p) => p.status === 'pending_approval') && <div className="mt-3"><Banner tone="amber">Awaiting human approval. <Link to="/approvals" className="font-medium underline">Open the Approval Center</Link></Banner></div>}
              </Card>
              {fixes.length > 1 && (
                <ChartCard title="Why the ranking looks this way" subtitle="Weighted contribution of each criterion to the utility score (root-cause actions)" table={{ headers: ['Action', 'Utility'], rows: fixes.map((f) => [f.title, f.utility.toFixed(3)]) }}>
                  <BarsChart layout="vertical" stacked height={Math.max(180, fixes.length * 52)} labelWidth={250} data={chart} xKey="name"
                    series={Object.keys(CRITERIA_LABEL).map((k) => ({ key: k, label: CRITERIA_LABEL[k] + (['business_risk', 'cost', 'execution_time'].includes(k) ? ' (penalty)' : ''), color: CRIT_COLOR[k] }))} />
                </ChartCard>
              )}
              {(['root_cause_fix', 'customer_mitigation', 'coordination'] as const).map((role) => {
                const rows = cur.filter((i) => i.role === role)
                if (!rows.length) return null
                return (
                  <Card key={role} title={ROLE_LABEL[role]} subtitle="Ranked by utility within the group" pad={false}>
                    <Table>
                      <thead><tr><Th>#</Th><Th>Action</Th><Th>Status</Th><Th>Expected impact</Th><Th>Cost</Th><Th>Time</Th><Th>Customers helped</Th><Th>Risk</Th><Th>Confidence</Th><Th>Reversible</Th><Th>Utility</Th><Th /></tr></thead>
                      <tbody>
                        {rows.map((iv) => (
                          <tr key={iv.id} className="hover:bg-slate-50">
                            <Td className="tnum">{iv.rank}</Td>
                            <Td className="max-w-xs"><button className="text-left font-medium hover:text-brand" onClick={() => setOpen(iv.id)}>{iv.title}</button>{iv.is_recommended && <Badge tone="blue" className="ml-2">Recommended</Badge>}{iv.is_consequential && <Badge tone="amber" className="ml-1">Approval</Badge>}</Td>
                            <Td><StatusBadge status={iv.status} /></Td>
                            <Td className="w-28"><Meter value={iv.expected_impact} /></Td>
                            <Td className="tnum">{inr(iv.cost_inr)}</Td><Td className="tnum">{iv.execution_hours}h</Td><Td className="tnum">{num(iv.customer_benefit)}</Td>
                            <Td className="w-24"><Meter value={iv.business_risk} tone="red" /></Td><Td className="tnum">{pct(iv.confidence)}</Td><Td className="tnum">{pct(iv.reversibility)}</Td><Td className="tnum font-medium">{iv.utility.toFixed(3)}</Td>
                            <Td>{iv.status === 'proposed' && can('analyst') && <Button size="sm" icon={<Send size={13} />} loading={submit.isPending && submit.variables === iv.id} onClick={() => submit.mutate(iv.id)}>Submit</Button>}</Td>
                          </tr>
                        ))}
                      </tbody>
                    </Table>
                  </Card>
                )
              })}
            </div>
          )
        }}
      </Async>
      <Drawer open={open != null} onClose={() => setOpen(null)} title="Intervention detail">{open != null && <IvDetail id={open} />}</Drawer>
    </>
  )
}
