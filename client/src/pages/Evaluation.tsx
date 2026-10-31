import { useQuery } from '@tanstack/react-query'
import { Banner, Async, Badge, Card, PageHeader, Stat, StatusBadge, Table, Td, Th } from '@/components/ui'
import { BarsChart, ChartCard } from '@/components/charts'
import { get } from '@/lib/api'
import { pct, title } from '@/lib/format'
import { CheckCircle2, Clock, Coins, Crosshair, FileCheck2, Gauge, ShieldCheck, Target, TrendingUp, XCircle } from 'lucide-react'

const P = (v: number | null | undefined, d = 0) => (v == null ? 'n/a' : pct(v, d))
const MS = (v: number | null | undefined) => (v == null ? 'n/a' : `${v < 10 ? v.toFixed(1) : Math.round(v)} ms`)

export default function Evaluation() {
  const q = useQuery({ queryKey: ['evaluation'], queryFn: () => get<any>('/evaluation'), staleTime: 0 })
  return (
    <>
      <PageHeader title="AI Evaluation Center" description="The platform is scored against a hidden, simulated benchmark with known ground truth. The investigation agents never see the ground truth." />
      <Async q={q}>
        {(e) => (
          <div className="space-y-5">
            {!e.benchmark_available && <Banner tone="amber">No benchmark ground truth is available for this dataset. Detection and root-cause accuracy cannot be scored for uploaded real data; runtime metrics below still apply.</Banner>}
            {e.detection && (
              <>
                <div>
                  <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-muted">Detection and diagnosis</h2>
                  <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-6">
                    <Stat label="Detection precision" value={P(e.detection.precision)} icon={<Crosshair size={15} />} hint={`${e.detection.true_positives} TP · ${e.detection.false_positives} FP`} />
                    <Stat label="Detection recall" value={P(e.detection.recall)} icon={<Target size={15} />} hint={`${e.detection.false_negatives} missed`} />
                    <Stat label="False-positive rate" value={P(e.detection.false_positive_rate)} tone="red" icon={<XCircle size={15} />} hint={`${e.detection.decoys_flagged_as_issues}/${e.detection.decoys_tested} decoys flagged`} />
                    <Stat label="Root-cause top-1" value={P(e.root_cause.top1_accuracy)} tone="teal" icon={<CheckCircle2 size={15} />} hint={`MRR ${e.root_cause.mean_reciprocal_rank?.toFixed(2) ?? 'n/a'} · top-3 ${P(e.root_cause.top3_recall)}`} />
                    <Stat label="Evidence groundedness" value={P(e.groundedness.ratio, 1)} tone="green" icon={<FileCheck2 size={15} />} hint={`${e.groundedness.grounded}/${e.groundedness.checked} claims reproduced`} />
                    <Stat label="Segmentation recall" value={P(e.segmentation.recall)} icon={<ShieldCheck size={15} />} hint={`precision@6 ${P(e.segmentation.precision_top6)}`} />
                  </div>
                </div>
                <Card title="Per-issue benchmark results" subtitle="Detected issue vs ground truth; ground-truth causes are revealed here only for scoring" pad={false}>
                  <Table>
                    <thead><tr><Th>Ground-truth issue</Th><Th>Detected</Th><Th>True cause</Th><Th>Rank of true cause</Th><Th>Top hypothesis</Th><Th>Onset error</Th><Th>Detection delay</Th><Th>Recommended action</Th><Th>Segments found</Th></tr></thead>
                    <tbody>{e.per_issue.map((r: any) => (
                      <tr key={r.ground_truth} className="align-top">
                        <Td className="font-medium">{r.category}</Td><Td>{r.detected ? <Badge tone="green">{r.detected}</Badge> : <Badge tone="red">missed</Badge>}</Td><Td className="text-xs">{title(r.true_cause)}</Td>
                        <Td className="tnum">{r.detected_rank_of_true_cause ?? '-'}</Td><Td className="max-w-xs text-xs">{r.top_hypothesis ?? '-'}{r.top_confidence != null && <span className="text-muted"> ({pct(r.top_confidence)})</span>}</Td>
                        <Td className="tnum">{r.onset_error_days != null ? `${r.onset_error_days}d` : '-'}</Td><Td className="tnum">{r.detection_delay_days != null ? `${r.detection_delay_days}d` : '-'}</Td>
                        <Td className="text-xs">{r.recommended_intervention ? title(r.recommended_intervention) : '-'} {r.recommendation_acceptable != null && <Badge tone={r.recommendation_acceptable ? 'green' : 'amber'}>{r.recommendation_acceptable ? 'acceptable' : 'review'}</Badge>}</Td>
                        <Td className="text-xs">{r.segmentation ? `${pct(r.segmentation.recall)} of expected (${r.segmentation.found.slice(0, 3).join(', ')})` : '-'}</Td>
                      </tr>))}</tbody>
                  </Table>
                </Card>
              </>
            )}
            <div>
              <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-muted">Operations and outcomes</h2>
              <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-6">
                <Stat label="Intervention acceptance" value={P(e.interventions.acceptance_rate)} icon={<ShieldCheck size={15} />} hint={`${e.interventions.approved} approved · ${e.interventions.rejected} rejected`} />
                <Stat label="Task completion" value={P(e.task_completion.completion_rate)} icon={<CheckCircle2 size={15} />} hint={`${e.task_completion.completed}/${e.task_completion.investigations} investigations`} />
                <Stat label="Agent success rate" value={P(e.task_completion.agent_success_rate, 1)} tone="green" icon={<Gauge size={15} />} hint={`${e.task_completion.agent_runs} agent runs`} />
                <Stat label="API latency p95" value={MS(e.api_latency.p95)} tone="teal" icon={<Clock size={15} />} hint={`p50 ${MS(e.api_latency.p50)} · ${e.api_latency.count} calls`} />
                <Stat label="Estimated AI cost" value={`$${e.ai_cost.estimated_usd.toFixed(4)}`} tone="amber" icon={<Coins size={15} />} hint={`${e.ai_cost.tokens_in + e.ai_cost.tokens_out} tokens · ${e.ai_cost.llm_provider}`} />
                <Stat label="Recovery success" value={P(e.recovery.success_rate)} tone="green" icon={<TrendingUp size={15} />} hint={`${e.recovery.recovered} recovered · ${e.recovery.not_recovered} failed`} />
              </div>
            </div>
            <div className="grid gap-5 xl:grid-cols-2">
              <ChartCard title="Agent latency" subtitle="Average duration per agent (ms)" table={{ headers: ['Agent', 'Avg ms', 'Max ms', 'Runs'], rows: e.agent_latency.map((a: any) => [a.agent, Math.round(a.avg_ms), a.max_ms, a.runs]) }}>
                <BarsChart layout="vertical" height={Math.max(200, e.agent_latency.length * 38)} labelWidth={200} data={e.agent_latency.map((a: any) => ({ name: a.agent.replace(' Agent', ''), ms: Math.round(a.avg_ms) }))} xKey="name" series={[{ key: 'ms', label: 'Average ms' }]} />
              </ChartCard>
              <Card title="Slowest API routes" subtitle="p95 latency from live traffic" pad={false}>
                <Table><thead><tr><Th>Route</Th><Th>Calls</Th><Th>p50</Th><Th>p95</Th></tr></thead>
                  <tbody>{e.api_latency.routes.map((r: any) => <tr key={r.route}><Td className="max-w-xs truncate font-mono text-xs">{r.route}</Td><Td className="tnum">{r.count}</Td><Td className="tnum">{MS(r.p50)}</Td><Td className="tnum">{MS(r.p95)}</Td></tr>)}</tbody></Table>
              </Card>
            </div>
            <Card title="Verified recovery and business KPI improvement" subtitle="Only interventions with enough post-intervention evidence are scored" pad={false}>
              {!e.recovery.details.length ? <p className="px-5 py-8 text-center text-sm text-muted">No intervention has been verified yet. Approve an intervention and advance the simulated clock in Recovery Monitoring.</p> : (
                <Table><thead><tr><Th>Intervention</Th><Th>KPI</Th><Th>Before</Th><Th>After</Th><Th>Verdict</Th></tr></thead>
                  <tbody>{e.recovery.details.map((r: any) => <tr key={r.intervention}><Td className="font-medium">{r.intervention}</Td><Td>{title(r.kpi)}</Td><Td className="tnum">{P(r.pre, 1)}</Td><Td className="tnum">{P(r.post, 1)}</Td><Td><StatusBadge status={r.verdict} /></Td></tr>)}</tbody></Table>)}
              <div className="border-t border-line-2 px-5 py-3 text-xs text-ink-2">Mean recovery time: <b>{e.recovery.mean_recovery_days == null ? 'n/a' : `${e.recovery.mean_recovery_days.toFixed(1)} days`}</b> · Mean KPI improvement on recovered cases: <b>{P(e.recovery.mean_kpi_improvement)}</b></div>
            </Card>
            <p className="text-xs text-muted">{e.ai_cost.note}</p>
          </div>
        )}
      </Async>
    </>
  )
}
