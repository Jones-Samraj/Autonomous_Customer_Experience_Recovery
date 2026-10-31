import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowRight, FlaskConical, Plus, Trash2 } from 'lucide-react'
import { get, post } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import { inr, num, pct, title } from '@/lib/format'
import type { Issue } from '@/lib/types'
import { Async, Badge, Banner, Button, Card, EmptyState, Field, inputCls, PageHeader, SeverityBadge, Table, Td, Th } from '@/components/ui'
import { toast } from '@/components/toast'

interface Schema { injections: { type: string; label: string; description: string; params: { name: string; label: string; type: string; default: any; options?: string[] }[] }[]; presets: { id: string; label: string; description: string; injections: { type: string; params: any }[] }[] }

function PairBar({ before, after }: { before: number | null; after: number | null }) {
  return (
    <div className="space-y-1">
      <div className="flex items-center gap-2"><div className="h-2 flex-1 overflow-hidden rounded-full bg-slate-100"><div className="h-full rounded-full bg-[#a8b3c4]" style={{ width: `${(before ?? 0) * 100}%` }} /></div><span className="tnum w-10 text-right text-xs text-ink-2">{before == null ? '-' : pct(before)}</span></div>
      <div className="flex items-center gap-2"><div className="h-2 flex-1 overflow-hidden rounded-full bg-slate-100"><div className="h-full rounded-full bg-[#2a78d6]" style={{ width: `${(after ?? 0) * 100}%` }} /></div><span className="tnum w-10 text-right text-xs font-semibold text-ink">{after == null ? '-' : pct(after)}</span></div>
    </div>
  )
}

const fmtImpact = (unit: string, v: number | null) => v == null ? '-' : unit === 'INR' ? inr(v) : unit === 'rate' || unit === 'probability' ? pct(v, 1) : unit === '0-100' ? v.toFixed(0) : num(v)

function Result({ s }: { s: any }) {
  const d = s.diff
  return (
    <div className="space-y-5">
      <Banner tone="blue" icon={<FlaskConical size={16} className="mt-0.5 shrink-0" />}>
        <p className="mb-1 font-semibold">What changed and why</p>
        <div className="space-y-1 whitespace-pre-line text-[13px]">{d.narrative}</div>
      </Banner>
      <div className="grid gap-4 md:grid-cols-3">
        <Card title="Injected evidence"><ul className="space-y-1 text-sm">{s.injected.injections.map((i: any, k: number) => <li key={k} className="text-ink-2">• {i.description}</li>)}</ul>
          <div className="mt-3 flex flex-wrap gap-1.5">{Object.entries(s.injected.records_by_type).map(([k, v]) => <Badge key={k} tone="violet">{String(v)} {title(k)}</Badge>)}{s.injected.events > 0 && <Badge tone="violet">{s.injected.events} event(s)</Badge>}{s.injected.flagged_prompt_injection > 0 && <Badge tone="red">{s.injected.flagged_prompt_injection} neutralised</Badge>}</div>
          <p className="mt-2 text-[11px] text-muted">Records were ingested through the normal pipeline (new records or revisions of existing ones) and every agent recomputed from the data.</p></Card>
        <Card title="Severity"><div className="flex items-center justify-between gap-2"><div className="text-center"><p className="text-[11px] text-muted">Original</p><SeverityBadge severity={d.severity.before.severity} /><p className="tnum mt-1 text-xl font-semibold">{d.severity.before.severity_score.toFixed(0)}</p></div>
          <ArrowRight className="text-muted" /><div className="text-center"><p className="text-[11px] text-muted">Updated</p><SeverityBadge severity={d.severity.after.severity} /><p className="tnum mt-1 text-xl font-semibold">{d.severity.after.severity_score.toFixed(0)}</p></div></div></Card>
        <Card title="Leading explanation"><p className="text-xs text-muted">Original</p><p className="mb-2 text-sm font-medium">{d.leading_before}</p><p className="text-xs text-muted">Updated</p><p className="text-sm font-medium text-brand">{d.leading_after}</p></Card>
      </div>
      <Card title="Hypotheses: original vs updated investigation" subtitle="Grey = before the evidence arrived, blue = after re-investigation" pad={false}>
        <Table><thead><tr><Th>Hypothesis</Th><Th className="w-64">Confidence</Th><Th>Change</Th><Th>Why</Th></tr></thead>
          <tbody>{d.hypotheses.map((h: any) => (
            <tr key={h.cause_type} className="align-top">
              <Td className="max-w-xs"><div className="font-medium">{h.title}</div><div className="text-[11px] text-muted">{h.before_status ? title(h.before_status) : 'new'} → {h.after_status ? title(h.after_status) : 'removed'}</div></Td>
              <Td><PairBar before={h.before} after={h.after} /></Td>
              <Td><Badge tone={h.change === 'down' ? 'red' : h.change === 'up' || h.change === 'new' ? 'blue' : 'neutral'}>{h.change === 'stable' ? 'No change' : `${h.delta >= 0 ? '+' : ''}${(h.delta * 100).toFixed(0)} pts`}</Badge></Td>
              <Td className="max-w-md text-[13px] text-ink-2">{h.reason}</Td>
            </tr>))}</tbody></Table>
      </Card>
      <div className="grid gap-5 xl:grid-cols-2">
        <Card title="Root-cause actions: ranking changes" pad={false}>
          <Table><thead><tr><Th>Action</Th><Th>Rank</Th><Th>Expected impact</Th></tr></thead>
            <tbody>{d.interventions.map((i: any) => <tr key={i.type}><Td>{i.title}{i.recommended && <Badge tone="blue" className="ml-2">Recommended</Badge>}</Td>
              <Td className="tnum">{i.before_rank ?? 'new'} → {i.after_rank}</Td><Td className="tnum">{pct(i.before_impact)} → {pct(i.after_impact)}</Td></tr>)}</tbody></Table>
          <div className="border-t border-line-2 px-4 py-3 text-sm"><span className="text-muted">Recommended before:</span> {d.recommended_before ?? '-'}<br /><span className="text-muted">Recommended now:</span> <b>{d.recommended_after ?? '-'}</b></div>
        </Card>
        <Card title="Business impact: before → after" pad={false}>
          <Table><thead><tr><Th>Metric</Th><Th>Before</Th><Th>After</Th></tr></thead>
            <tbody>{Object.entries(d.impact).map(([k, v]: any) => <tr key={k}><Td>{v.label}<Badge tone={v.kind === 'measured' ? 'green' : 'violet'} className="ml-2">{v.kind}</Badge></Td><Td className="tnum">{fmtImpact(v.unit, v.before)}</Td><Td className="tnum font-medium">{fmtImpact(v.unit, v.after)}</Td></tr>)}</tbody></Table>
        </Card>
      </div>
    </div>
  )
}

export default function Simulator() {
  const { can } = useAuth()
  const qc = useQueryClient()
  const issues = useQuery({ queryKey: ['issues'], queryFn: () => get<Issue[]>('/issues') })
  const schema = useQuery({ queryKey: ['scenario-schema'], queryFn: () => get<Schema>('/scenarios/schema') })
  const past = useQuery({ queryKey: ['scenarios'], queryFn: () => get<any[]>('/scenarios') })
  const [issueId, setIssueId] = useState<number | null>(null)
  const [custom, setCustom] = useState<{ type: string; params: Record<string, any> }[]>([])
  const [adding, setAdding] = useState('')
  const [result, setResult] = useState<any>(null)
  const sel = issueId ?? issues.data?.find((i) => i.aspect === 'delivery')?.id ?? issues.data?.[0]?.id ?? null
  const run = useMutation({
    mutationFn: (body: any) => post('/scenarios/run', body),
    onSuccess: (r) => { setResult(r); toast.success('Re-investigation complete'); qc.invalidateQueries() },
    onError: toast.error,
  })
  const load = async (id: number) => setResult(await get(`/scenarios/${id}`))
  if (!can('analyst')) return <Banner tone="amber">The jury simulator requires the analyst or approver role.</Banner>
  return (
    <>
      <PageHeader title="Dynamic Jury Simulator" description="Introduce unexpected evidence while an investigation is in progress. The platform ingests it, recomputes severity, segments, hypotheses, impact and the intervention ranking, then shows the original and updated investigation side by side. Nothing here is scripted."
        actions={issues.data && <Field label="Investigation"><select className={`${inputCls} w-72`} value={sel ?? ''} onChange={(e) => setIssueId(Number(e.target.value))}>{issues.data.filter((i) => i.status !== 'watchlist').map((i) => <option key={i.id} value={i.id}>{i.code} · {i.category}</option>)}</select></Field>} />
      <Async q={schema}>
        {(sc) => (
          <div className="space-y-5">
            <div className="grid gap-5 xl:grid-cols-2">
              <Card title="Quick scenarios" subtitle="One click, composed of real injections">
                <div className="space-y-3">{sc.presets.map((p) => (
                  <div key={p.id} className="rounded-xl border border-line p-3">
                    <div className="flex items-start justify-between gap-3"><div><p className="text-sm font-semibold">{p.label}</p><p className="mt-0.5 text-xs text-ink-2">{p.description}</p>
                      <div className="mt-1.5 flex flex-wrap gap-1">{p.injections.map((i, k) => <Badge key={k} tone="neutral">{title(i.type)}</Badge>)}</div></div>
                      <Button variant="primary" size="sm" disabled={!sel} loading={run.isPending && run.variables?.preset === p.id} onClick={() => run.mutate({ issue_id: sel, preset: p.id })}>Inject &amp; re-investigate</Button></div>
                  </div>))}</div>
              </Card>
              <Card title="Custom evidence" subtitle="Combine any injections, then run them together">
                <div className="space-y-3">
                  {custom.map((c, i) => {
                    const def = sc.injections.find((x) => x.type === c.type)!
                    return (
                      <div key={i} className="rounded-xl border border-line p-3">
                        <div className="mb-2 flex items-center justify-between"><p className="text-sm font-semibold">{def.label}</p><button aria-label="Remove" onClick={() => setCustom(custom.filter((_, k) => k !== i))} className="rounded p-1 text-muted hover:bg-slate-100"><Trash2 size={14} /></button></div>
                        <div className="grid gap-2 sm:grid-cols-2">{def.params.map((p) => (
                          <Field key={p.name} label={p.label}>
                            {p.type === 'select' ? <select className={inputCls} value={c.params[p.name]} onChange={(e) => setCustom(custom.map((x, k) => k === i ? { ...x, params: { ...x.params, [p.name]: e.target.value } } : x))}>{p.options!.map((o) => <option key={o}>{o}</option>)}</select>
                              : p.type === 'textarea' ? <textarea className={`${inputCls} h-24 py-2`} value={c.params[p.name]} onChange={(e) => setCustom(custom.map((x, k) => k === i ? { ...x, params: { ...x.params, [p.name]: e.target.value } } : x))} />
                              : <input className={inputCls} type={p.type === 'number' ? 'number' : 'text'} step="any" value={c.params[p.name]} onChange={(e) => setCustom(custom.map((x, k) => k === i ? { ...x, params: { ...x.params, [p.name]: p.type === 'number' ? Number(e.target.value) : e.target.value } } : x))} />}
                          </Field>))}</div>
                      </div>
                    )
                  })}
                  <div className="flex gap-2">
                    <select className={inputCls} value={adding} onChange={(e) => setAdding(e.target.value)}><option value="">Add an injection...</option>{sc.injections.map((i) => <option key={i.type} value={i.type}>{i.label}</option>)}</select>
                    <Button icon={<Plus size={14} />} disabled={!adding} onClick={() => { const d = sc.injections.find((x) => x.type === adding)!; setCustom([...custom, { type: adding, params: Object.fromEntries(d.params.map((p) => [p.name, p.default])) }]); setAdding('') }}>Add</Button>
                  </div>
                  <Button variant="primary" disabled={!custom.length || !sel} loading={run.isPending && !run.variables?.preset} onClick={() => run.mutate({ issue_id: sel, name: 'Custom scenario', injections: custom })}>Run custom scenario</Button>
                </div>
              </Card>
            </div>
            {run.isPending && <Banner tone="blue">Ingesting evidence and re-running the agents. This takes a few seconds...</Banner>}
            {result ? <Result s={result} /> : <Card><EmptyState title="No scenario run yet" hint="Pick a quick scenario to see the original and updated investigation side by side." icon={<FlaskConical size={18} />} /></Card>}
            <Card title="Previous scenarios" pad={false}>
              <Async q={past}>{(rows) => !rows.length ? <EmptyState title="None yet" /> : (
                <Table><thead><tr><Th>#</Th><Th>Scenario</Th><Th>Summary</Th><Th /></tr></thead>
                  <tbody>{rows.map((r) => <tr key={r.id}><Td>{r.id}</Td><Td className="font-medium">{r.name}</Td><Td className="max-w-xl text-xs text-ink-2">{r.narrative}</Td><Td><Button size="sm" variant="ghost" onClick={() => load(r.id)}>View</Button></Td></tr>)}</tbody></Table>)}</Async>
            </Card>
          </div>
        )}
      </Async>
    </>
  )
}
