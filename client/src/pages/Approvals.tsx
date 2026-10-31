import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, CheckCircle2, ShieldCheck, X, XCircle } from 'lucide-react'
import { get, post } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import { date, inr, pct } from '@/lib/format'
import type { Approval } from '@/lib/types'
import { Async, Badge, Banner, Button, Card, Drawer, EmptyState, inputCls, PageHeader, SeverityBadge, StatusBadge, Table, Td, Th } from '@/components/ui'
import { toast } from '@/components/toast'

function PendingCard({ a }: { a: Approval }) {
  const { can } = useAuth()
  const qc = useQueryClient()
  const [comment, setComment] = useState('')
  const h = a.target_hypothesis
  const decide = useMutation({
    mutationFn: (ok: boolean) => post(`/approvals/${a.id}/${ok ? 'approve' : 'reject'}`, { comment: comment || null }),
    onSuccess: (_, ok) => { toast.success(ok ? 'Approved. The Execution agent is running the simulated tools.' : 'Rejected'); qc.invalidateQueries() },
    onError: toast.error,
  })
  const iv = a.intervention
  return (
    <Card>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex flex-wrap items-center gap-2 text-xs text-muted"><span className="font-medium text-ink-2">{a.issue?.code} · {iv.code}</span>{a.issue && <SeverityBadge severity={a.issue.severity} />}<StatusBadge status="pending" /><span>requested {date(a.requested_at, true)}</span></div>
          <h3 className="mt-1.5 text-base font-semibold">{iv.title}</h3>
          <p className="mt-1 max-w-3xl text-sm text-ink-2">{iv.rationale}</p>
        </div>
        <dl className="grid grid-cols-2 gap-x-6 gap-y-1 text-sm">
          <dt className="text-muted">Cost</dt><dd className="tnum text-right font-medium">{inr(iv.cost_inr)}</dd><dt className="text-muted">Expected impact</dt><dd className="tnum text-right font-medium">{pct(iv.expected_impact)}</dd>
          <dt className="text-muted">Business risk</dt><dd className="tnum text-right font-medium">{pct(iv.business_risk)}</dd><dt className="text-muted">Reversibility</dt><dd className="tnum text-right font-medium">{pct(iv.reversibility)}</dd>
          <dt className="text-muted">Execution time</dt><dd className="tnum text-right font-medium">{iv.execution_hours}h</dd>
        </dl>
      </div>
      {h && (
        <div className="mt-4 grid gap-4 border-t border-line-2 pt-4 lg:grid-cols-2">
          <div>
            <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted">Evidence behind the recommendation</p>
            <p className="mb-2 text-sm"><b>{h.title}</b> - {pct(h.confidence)} confidence, {h.quality_label} evidence quality. <span className="text-ink-2">{h.causal_claim}</span></p>
            <ul className="space-y-1.5">{h.supporting_evidence.slice(0, 3).map((e) => <li key={e.id} className="flex gap-2 text-[13px]"><CheckCircle2 size={14} className="mt-0.5 shrink-0 text-good" />{e.summary}</li>)}</ul>
          </div>
          <div>
            <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted">Counter-evidence and uncertainty</p>
            <ul className="space-y-1.5">{h.contradicting_evidence.slice(0, 3).map((e) => <li key={e.id} className="flex gap-2 text-[13px]"><XCircle size={14} className="mt-0.5 shrink-0 text-critical" />{e.summary}</li>)}
              {!h.contradicting_evidence.length && <li className="text-[13px] text-muted">No direct contradicting evidence; alternatives are listed in the investigation.</li>}</ul>
          </div>
        </div>
      )}
      <div className="mt-4 border-t border-line-2 pt-4">
        {can('approver') ? (
          <div className="flex flex-wrap items-end gap-3">
            <label className="min-w-64 flex-1"><span className="mb-1 block text-xs font-medium text-ink-2">Decision comment (recorded in the audit trail)</span><input className={inputCls} value={comment} onChange={(e) => setComment(e.target.value)} placeholder="Optional reasoning" /></label>
            <Button variant="danger" icon={<X size={15} />} loading={decide.isPending && decide.variables === false} onClick={() => decide.mutate(false)}>Reject</Button>
            <Button variant="primary" icon={<Check size={15} />} loading={decide.isPending && decide.variables === true} onClick={() => decide.mutate(true)}>Approve &amp; execute</Button>
          </div>
        ) : <Banner tone="amber">Only users with the approver role can decide on consequential actions.</Banner>}
      </div>
    </Card>
  )
}

export default function Approvals() {
  const [open, setOpen] = useState<Approval | null>(null)
  const q = useQuery({ queryKey: ['approvals', 'all'], queryFn: () => get<Approval[]>('/approvals') })
  return (
    <>
      <PageHeader title="Human Approval Center" description="Consequential financial or operational actions wait here. Approving triggers execution through simulated enterprise tools with retries, idempotency and rollback." />
      <Async q={q}>
        {(all) => {
          const pending = all.filter((a) => a.status === 'pending')
          const hist = all.filter((a) => a.status !== 'pending')
          return (
            <div className="space-y-5">
              <div className="space-y-4">
                <h2 className="text-base font-semibold">Pending ({pending.length})</h2>
                {!pending.length ? <Card><EmptyState title="No pending approvals" hint="Run an investigation and the recommended package will appear here." icon={<ShieldCheck size={18} />} /></Card> : pending.map((a) => <PendingCard key={a.id} a={a} />)}
              </div>
              <Card title="Approval history" subtitle="Decisions, execution status and audit comments" pad={false}>
                {!hist.length ? <EmptyState title="No decisions yet" /> : (
                  <Table><thead><tr><Th>Request</Th><Th>Intervention</Th><Th>Decision</Th><Th>Decided by</Th><Th>When</Th><Th>Execution</Th><Th>Verification</Th><Th /></tr></thead>
                    <tbody>{hist.map((a) => (
                      <tr key={a.id} className="hover:bg-slate-50">
                        <Td className="tnum">#{a.id}<div className="text-[11px] text-muted">{a.issue?.code}</div></Td><Td className="max-w-xs">{a.intervention.title}<div className="text-[11px] text-muted">{a.intervention.code}</div></Td>
                        <Td><StatusBadge status={a.status} /></Td><Td>{a.decided_by_name ?? <Badge tone="neutral">policy</Badge>}</Td><Td className="whitespace-nowrap text-xs">{date(a.decided_at, true)}</Td>
                        <Td><StatusBadge status={a.intervention.status} /></Td><Td><StatusBadge status={a.intervention.verification_status} /></Td>
                        <Td><Button size="sm" variant="ghost" onClick={() => setOpen(a)}>Details</Button></Td>
                      </tr>))}</tbody></Table>
                )}
              </Card>
            </div>
          )
        }}
      </Async>
      <Drawer open={!!open} onClose={() => setOpen(null)} title={open ? `${open.intervention.code} · ${open.intervention.title}` : ''}>
        {open && <div className="space-y-3 text-sm"><div className="flex gap-2"><StatusBadge status={open.status} /><StatusBadge status={open.intervention.status} /></div>
          <p className="text-ink-2">{open.intervention.rationale}</p><p><b>Comment:</b> {open.comment ?? '-'}</p><pre className="max-h-72 overflow-auto rounded-lg bg-slate-50 p-3 text-xs">{JSON.stringify(open.summary, null, 2)}</pre></div>}
      </Drawer>
    </>
  )
}
