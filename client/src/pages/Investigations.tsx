import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, CheckCircle2, Database, Lightbulb, RefreshCw, ShieldQuestion, XCircle } from 'lucide-react'
import { get, post } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import { date, pct, title } from '@/lib/format'
import type { Evidence, Hypothesis, Investigation, Issue } from '@/lib/types'
import { Async, Badge, Banner, Button, Card, Disclosure, EmptyState, Meter, PageHeader, SeverityBadge, StatusBadge, Table, Tabs, Td, Th } from '@/components/ui'
import EvidenceGraph from '@/components/EvidenceGraph'
import { ActivityTimeline, AgentRunsTable } from '@/components/AgentTimeline'
import { toast } from '@/components/toast'

const OBSERVED = new Set(['statistic', 'event', 'release', 'metric', 'complaint_sample'])

function EvidenceList({ items, tone }: { items: Evidence[]; tone: 'supports' | 'contradicts' }) {
  if (!items.length) return <p className="rounded-lg bg-slate-50 px-3 py-3 text-xs text-muted">{tone === 'supports' ? 'No supporting evidence.' : 'No contradicting evidence found.'}</p>
  return (
    <ul className="space-y-2">
      {items.slice(0, 6).map((e) => (
        <li key={e.id} className="rounded-lg border border-line-2 bg-white p-2.5 text-[13px]">
          <div className="flex items-start gap-2">
            {tone === 'supports' ? <CheckCircle2 size={15} className="mt-0.5 shrink-0 text-good" /> : <XCircle size={15} className="mt-0.5 shrink-0 text-critical" />}
            <div className="min-w-0">
              <p className="text-ink">{e.summary}</p>
              <div className="mt-1 flex flex-wrap items-center gap-1.5 text-[11px] text-muted">
                <Badge tone={OBSERVED.has(e.kind) ? 'green' : 'neutral'}>{OBSERVED.has(e.kind) ? 'Observed' : 'Inferred'}</Badge>{title(e.kind)}
                {e.event_id && <span>event #{e.event_id}</span>}{e.release_id && <span>release #{e.release_id}</span>}{e.signal_id && <span>signal #{e.signal_id}</span>}
                {e.payload?.n != null && <span className="tnum">n={e.payload.n}</span>}
              </div>
            </div>
          </div>
        </li>
      ))}
    </ul>
  )
}

function HypothesisCard({ h }: { h: Hypothesis }) {
  const f = h.features ?? {}
  const tone = h.status === 'leading' ? 'blue' : h.status === 'refuted' ? 'red' : h.status === 'insufficient_data' ? 'amber' : 'teal'
  return (
    <Card className={h.rank === 1 && h.status === 'leading' ? 'ring-2 ring-brand/20' : ''}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2"><span className="grid size-6 place-items-center rounded-full bg-ink text-xs font-semibold text-white">{h.rank}</span><StatusBadge status={h.status} /><Badge tone="neutral">{title(h.cause_type)}</Badge><Badge tone={h.quality_label === 'high' ? 'green' : h.quality_label === 'medium' ? 'amber' : 'red'} icon={<Database size={11} />}>{title(h.quality_label)} evidence quality</Badge></div>
          <h3 className="mt-2 text-base font-semibold">{h.title}</h3>
          <p className="mt-1 text-sm text-ink-2">{h.statement}</p>
        </div>
        <div className="w-44 shrink-0 text-right">
          <div className="text-[11px] font-medium uppercase tracking-wide text-muted">Confidence</div>
          <div className="tnum text-3xl font-semibold" style={{ color: tone === 'blue' ? '#1d4ed8' : undefined }}>{pct(h.confidence)}</div>
          <Meter value={h.confidence} tone={h.confidence > 0.6 ? 'blue' : h.confidence > 0.3 ? 'teal' : 'amber'} />
        </div>
      </div>
      <Banner tone={h.causal_claim.includes('not proven') || h.causal_claim.includes('cannot') ? 'amber' : 'blue'} icon={<ShieldQuestion size={16} className="mt-0.5 shrink-0" />}>
        <span className="font-medium">Correlation vs causation:</span> {h.causal_claim}
      </Banner>
      {h.narrative && <p className="mt-3 rounded-lg bg-slate-50 p-3 text-[13px] text-ink-2">{h.narrative}</p>}
      {f.exposed_n > 0 && (
        <div className="mt-3 flex flex-wrap gap-2 text-xs">
          <Badge tone="neutral">Coverage of excess {pct(f.coverage)}</Badge>
          <Badge tone="neutral">Adjusted attribution {f.attribution == null ? 'n/a (no control)' : pct(f.attribution)}</Badge>
          <Badge tone={f.residual > 0.2 ? 'red' : 'neutral'}>Unexplained excess {pct(f.residual)}</Badge>
          <Badge tone="neutral">{f.has_control ? 'Concurrent control group' : 'No concurrent control'}</Badge>
          <Badge tone="neutral">n = {f.exposed_n}</Badge>
        </div>
      )}
      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <div><p className="mb-2 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-good"><CheckCircle2 size={13} />Supporting evidence ({h.supporting_evidence.length})</p><EvidenceList items={h.supporting_evidence} tone="supports" /></div>
        <div><p className="mb-2 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-critical"><XCircle size={13} />Contradicting evidence ({h.contradicting_evidence.length})</p><EvidenceList items={h.contradicting_evidence} tone="contradicts" /></div>
      </div>
      <div className="mt-4 grid gap-4 border-t border-line-2 pt-4 lg:grid-cols-2">
        <Disclosure summary={<span className="text-sm font-medium">Alternative explanations ({h.alternatives?.length ?? 0})</span>}>
          <ul className="space-y-1.5 text-[13px]">{h.alternatives?.map((a, i) => <li key={i} className="flex items-start justify-between gap-3"><span className="text-ink-2">{a.title}{a.note && <span className="block text-[11px] text-muted">{a.note}</span>}</span><span className="tnum shrink-0 font-medium">{pct(a.confidence)}</span></li>)}</ul>
        </Disclosure>
        <Disclosure summary={<span className="text-sm font-medium">Additional data needed ({h.additional_data_needed?.length ?? 0})</span>}>
          <ul className="list-disc space-y-1 pl-5 text-[13px] text-ink-2">{h.additional_data_needed?.map((d, i) => <li key={i}>{d}</li>)}</ul>
        </Disclosure>
      </div>
    </Card>
  )
}

function Detail({ id }: { id: number }) {
  const { can } = useAuth()
  const qc = useQueryClient()
  const [tab, setTab] = useState<'hyp' | 'graph' | 'segments' | 'timeline' | 'history'>('hyp')
  const q = useQuery({ queryKey: ['investigation', id], queryFn: () => get<Investigation>(`/investigations/${id}`) })
  const g = useQuery({ queryKey: ['graph', id, q.data?.iteration, q.data?.hypotheses.length], queryFn: () => get<any>(`/investigations/${id}/graph`), enabled: tab === 'graph' })
  const rerun = useMutation({ mutationFn: () => post(`/investigations/${id}/run`), onSuccess: () => { toast.success('Investigation re-run complete'); qc.invalidateQueries() }, onError: toast.error })
  return (
    <Async q={q}>
      {(inv) => {
        const i = inv.issue as Issue
        return (
          <>
            <PageHeader title={`${i.code} · ${i.title}`} description={i.description}
              actions={<><SeverityBadge severity={i.severity} /><StatusBadge status={inv.status} /><Badge tone="neutral">Iteration {inv.iteration}</Badge>
                {can('analyst') && <Button icon={<RefreshCw size={14} />} loading={rerun.isPending} onClick={() => rerun.mutate()}>Re-run investigation</Button>}</>} />
            {i.status === 'reopened' || i.reopen_count > 0 ? <div className="mb-4"><Banner tone="red" icon={<AlertTriangle size={16} className="mt-0.5 shrink-0" />}>This investigation was re-opened {i.reopen_count}× because an executed intervention did not restore the KPI. The failed cause is down-weighted using interventional evidence.</Banner></div> : null}
            <Tabs value={tab} onChange={setTab} tabs={[{ id: 'hyp', label: 'Hypotheses', count: inv.hypotheses.length }, { id: 'graph', label: 'Evidence graph' }, { id: 'segments', label: 'Impacted segments' }, { id: 'timeline', label: 'Investigation timeline' }, { id: 'history', label: 'Agent decisions', count: inv.history.length }]} />
            {tab === 'hyp' && (
              <div className="space-y-4">
                <div className="flex flex-wrap items-center gap-2 text-xs text-ink-2"><span className="font-medium">Reading guide:</span><Badge tone="green">Observed</Badge>measured in data<Badge tone="neutral">Inferred</Badge>hypothesis or model output<Badge tone="violet">Predicted</Badge>estimated outcome (see Impact)</div>
                {!inv.hypotheses.length ? <Card><EmptyState title="No hypotheses yet" hint="Run the investigation to generate and score competing explanations." icon={<Lightbulb size={18} />} /></Card> : inv.hypotheses.map((h) => <HypothesisCard key={h.id} h={h} />)}
                {Object.keys(inv.previous_hypotheses).length > 0 && (
                  <Card title="Earlier iterations" subtitle="How the explanation changed as new evidence arrived" pad={false}>
                    <Table><thead><tr><Th>Iteration</Th><Th>Hypothesis</Th><Th>Confidence</Th><Th>Status</Th></tr></thead>
                      <tbody>{Object.entries(inv.previous_hypotheses).sort((a, b) => Number(b[0]) - Number(a[0])).flatMap(([it, hs]) => hs.slice(0, 3).map((h: any) => <tr key={`${it}-${h.id}`}><Td>#{it}</Td><Td>{h.title}</Td><Td className="tnum">{pct(h.confidence)}</Td><Td><StatusBadge status={h.status} /></Td></tr>))}</tbody></Table>
                  </Card>
                )}
                <div className="flex gap-2"><Link to="/impact"><Button>Customer impact</Button></Link><Link to="/interventions"><Button variant="primary">Intervention options</Button></Link></div>
              </div>
            )}
            {tab === 'graph' && <Card title="Evidence graph" subtitle="Signals, operational events, releases, metrics, hypotheses, the issue, segments and interventions">
              <Async q={g}>{(gr) => <EvidenceGraph graph={gr} />}</Async></Card>}
            {tab === 'segments' && (
              <Card title="Over-represented customer groups" subtitle={inv.segmentation ? `${inv.segmentation.affected_customers} of ${inv.segmentation.active_customers} active customers affected (${pct(inv.segmentation.affected_rate, 1)})` : undefined} pad={false}>
                {!inv.segmentation?.segments.length ? <EmptyState title="No segment analysis yet" /> : (
                  <>
                    <Table><thead><tr><Th>Dimension</Th><Th>Group</Th><Th>Customers</Th><Th>Affected</Th><Th>Rate</Th><Th>Lift</Th><Th>Adj. p</Th><Th>Severity</Th></tr></thead>
                      <tbody>{inv.segmentation.segments.map((s, k) => <tr key={k}><Td>{s.label}</Td><Td className="font-medium">{s.value}</Td><Td className="tnum">{s.customers}</Td><Td className="tnum">{s.affected}</Td><Td className="tnum">{pct(s.rate)}</Td><Td className="tnum">{s.lift.toFixed(1)}x</Td><Td className="tnum">{s.p_adj < 0.001 ? '<0.001' : s.p_adj.toFixed(3)}</Td><Td><StatusBadge status={s.severity} /></Td></tr>)}</tbody></Table>
                    <div className="border-t border-line-2 p-4"><p className="mb-1 text-xs font-semibold text-muted">Privacy &amp; fairness guard-rails</p><ul className="list-disc space-y-0.5 pl-5 text-xs text-ink-2">{inv.segmentation.privacy_notes.map((n) => <li key={n}>{n}</li>)}</ul></div>
                  </>
                )}
              </Card>
            )}
            {tab === 'timeline' && <Card title="Investigation timeline" subtitle="Agent runs, approvals, executions and scenarios in order"><ActivityTimeline items={inv.timeline} /></Card>}
            {tab === 'history' && <Card title="Agent execution history" subtitle="Task, input evidence, reasoning summary, output and status for every agent step" pad={false}><AgentRunsTable runs={inv.history} /></Card>}
            <p className="mt-4 text-xs text-muted">Evidence on this page is point-in-time reproducible: every statistic is recomputed from the stored records when validated (see AI Evaluation → groundedness).</p>
          </>
        )
      }}
    </Async>
  )
}

export default function Investigations() {
  const { id } = useParams()
  const nav = useNavigate()
  const q = useQuery({ queryKey: ['issues'], queryFn: () => get<Issue[]>('/issues') })
  if (id) return <Detail id={Number(id)} />
  return (
    <>
      <PageHeader title="Root Cause Investigation" description="Competing hypotheses scored on timing, coverage, adjusted effect against a control group, and direct measurements. Confidence is capped below certainty - nothing is claimed as proven." />
      <Async q={q}>{(issues) => !issues.length ? <Card><EmptyState title="No issues to investigate" hint="Detect issues first." /></Card> : (
        <Card pad={false}>
          <Table><thead><tr><Th>Issue</Th><Th>Severity</Th><Th>Leading hypothesis</Th><Th>Confidence</Th><Th>Status</Th><Th>Updated</Th></tr></thead>
            <tbody>{issues.map((i) => (
              <tr key={i.id} className="cursor-pointer hover:bg-slate-50" onClick={() => nav(`/investigations/${i.id}`)}>
                <Td><span className="font-medium text-brand">{i.code}</span><div className="max-w-sm truncate text-xs text-ink-2">{i.title}</div></Td><Td><SeverityBadge severity={i.severity} /></Td>
                <Td className="max-w-md">{i.top_hypothesis?.title ?? <span className="text-muted">Not investigated</span>}</Td><Td className="w-32">{i.top_hypothesis ? <Meter value={i.top_hypothesis.confidence} /> : '-'}</Td>
                <Td><StatusBadge status={i.status} /></Td><Td className="text-xs text-ink-2">{date(i.updated_at, true)}</Td>
              </tr>))}</tbody></Table>
        </Card>)}</Async>
    </>
  )
}
