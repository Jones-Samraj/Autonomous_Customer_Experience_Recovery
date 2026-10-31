import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  AlertOctagon, CheckCheck, Coins, Play, ShieldCheck, Users, Radar, Microscope,
  Database, Cpu, Calculator, ExternalLink, ArrowRight
} from 'lucide-react'
import { get, post } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import { date, inr, num, pct, shortDay } from '@/lib/format'
import type { Approval, Issue, KpiSeries } from '@/lib/types'
import { Async, Badge, Button, Card, Drawer, EmptyState, SeverityBadge, Stat, StatusBadge, Table, Td, Th } from '@/components/ui'
import { BarsChart, ChartCard, SEVERITY_COLOR, TrendChart, toTable } from '@/components/charts'
import { toast } from '@/components/toast'

interface Overview {
  sim_now: string
  kpis: {
    total_issues: number
    critical_issues: number
    watchlist: number
    affected_customers: number
    revenue_at_risk: number
    active_investigations: number
    pending_approvals: number
    recovery_success_rate: number | null
    verified_outcomes: number
  }
  issues_by_severity: { severity: string; count: number }[]
  revenue_by_issue: { issue: string; title: string; revenue_at_risk: number; affected: number; severity: string }[]
  recent_incidents: Issue[]
  trends: KpiSeries[]
}

type InspectMetric =
  | 'total_issues'
  | 'critical_issues'
  | 'affected_customers'
  | 'revenue_at_risk'
  | 'active_investigations'
  | 'pending_approvals'
  | 'recovery_success'

function merge(trends: KpiSeries[], codes: string[]) {
  const by: Record<string, any> = {}
  trends.filter((t) => codes.includes(t.code)).forEach((t) => t.series.forEach((p) => { (by[p.date] ??= { date: p.date })[t.code] = Number(p.value.toFixed(2)) }))
  return Object.values(by).sort((a, b) => a.date.localeCompare(b.date))
}

export default function Overview() {
  const { can } = useAuth()
  const qc = useQueryClient()
  const [inspectKey, setInspectKey] = useState<InspectMetric | null>(null)
  const q = useQuery({ queryKey: ['overview'], queryFn: () => get<Overview>('/dashboard/overview') })
  const pend = useQuery({ queryKey: ['approvals', 'pending'], queryFn: () => get<Approval[]>('/approvals', { status: 'pending' }) })
  const allIssues = useQuery({
    queryKey: ['issues'],
    queryFn: () => get<Issue[]>('/issues'),
    enabled: inspectKey !== null,
  })

  const run = useMutation({
    mutationFn: () => post('/pipeline/run'),
    onSuccess: () => {
      toast.info('Full analysis started: agents are detecting, investigating and planning. Progress appears live.')
      setTimeout(() => qc.invalidateQueries(), 4000)
    },
    onError: toast.error,
  })

  return (
    <>
      <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-[22px] font-semibold">Executive Overview</h1>
          <p className="mt-1 text-sm text-ink-2">
            Every figure is computed from ingested evidence. Click any card to inspect where the data comes from and its underlying formulas.
          </p>
        </div>
        {can('analyst') && (
          <Button variant="primary" icon={<Play size={15} />} loading={run.isPending} onClick={() => run.mutate()}>
            Run full analysis
          </Button>
        )}
      </div>

      <Async q={q}>
        {(o) => {
          const k = o.kpis
          if (!k.total_issues && !o.recent_incidents.length) {
            return (
              <Card>
                <EmptyState
                  title="No issues detected yet"
                  hint="Load the sample datasets in the Signal Explorer, then run the full analysis to detect and investigate emerging problems."
                  action={
                    <Link to="/signals">
                      <Button variant="primary">Open Signal Explorer</Button>
                    </Link>
                  }
                />
              </Card>
            )
          }

          const issuesList = allIssues.data ?? o.recent_incidents
          const criticalIssues = issuesList.filter((i) => i.severity === 'critical')
          const activeIssues = issuesList.filter((i) => i.status !== 'resolved' && i.status !== 'superseded' && i.status !== 'watchlist')

          return (
            <div className="space-y-5">
              {/* Top 7 Metric Cards with Click to Inspect */}
              <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-7">
                <Stat
                  label="Detected issues"
                  value={k.total_issues}
                  hint={k.watchlist ? `${k.watchlist} on watchlist` : 'none on watchlist'}
                  icon={<Radar size={15} />}
                  onClick={() => setInspectKey('total_issues')}
                />
                <Stat
                  label="Critical"
                  value={k.critical_issues}
                  tone="red"
                  icon={<AlertOctagon size={15} />}
                  hint="severity score ≥ 75"
                  onClick={() => setInspectKey('critical_issues')}
                />
                <Stat
                  label="Affected customers"
                  value={num(k.affected_customers)}
                  tone="teal"
                  icon={<Users size={15} />}
                  hint="measured, open issues"
                  onClick={() => setInspectKey('affected_customers')}
                />
                <Stat
                  label="Revenue at risk"
                  value={inr(k.revenue_at_risk)}
                  tone="amber"
                  icon={<Coins size={15} />}
                  hint="estimated, 3-month horizon"
                  onClick={() => setInspectKey('revenue_at_risk')}
                />
                <Stat
                  label="Active investigations"
                  value={k.active_investigations}
                  icon={<Microscope size={15} />}
                  onClick={() => setInspectKey('active_investigations')}
                />
                <Stat
                  label="Pending approvals"
                  value={k.pending_approvals}
                  tone="amber"
                  icon={<ShieldCheck size={15} />}
                  hint={<span className="text-brand">Review details</span>}
                  onClick={() => setInspectKey('pending_approvals')}
                />
                <Stat
                  label="Recovery success"
                  value={k.recovery_success_rate == null ? 'n/a' : pct(k.recovery_success_rate)}
                  tone="green"
                  icon={<CheckCheck size={15} />}
                  hint={k.verified_outcomes ? `${k.verified_outcomes} verified outcome(s)` : 'no verified outcomes yet'}
                  onClick={() => setInspectKey('recovery_success')}
                />
              </div>

              {/* Charts Row 1 */}
              <div className="grid gap-5 xl:grid-cols-3">
                <ChartCard
                  title="Complaint volume"
                  subtitle="Negative customer-voice signals per day"
                  className="xl:col-span-2"
                  table={toTable(merge(o.trends, ['complaint_volume']), 'date', [{ key: 'complaint_volume', label: 'Complaints' }])}
                >
                  <TrendChart
                    data={merge(o.trends, ['complaint_volume'])}
                    xFmt={shortDay}
                    series={[{ key: 'complaint_volume', label: 'Complaints per day' }]}
                    baseline={o.trends.find((t) => t.code === 'complaint_volume')?.baseline}
                    baselineLabel="14-day baseline"
                  />
                </ChartCard>
                <ChartCard
                  title="Issues by severity"
                  subtitle="Confirmed issues"
                  table={{ headers: ['Severity', 'Issues'], rows: o.issues_by_severity.map((s) => [s.severity, s.count]) }}
                >
                  <BarsChart
                    data={o.issues_by_severity}
                    xKey="severity"
                    series={[{ key: 'count', label: 'Issues' }]}
                    height={220}
                    colorByRow={(r) => SEVERITY_COLOR[r.severity]}
                  />
                </ChartCard>
              </div>

              {/* Charts Row 2 */}
              <div className="grid gap-5 xl:grid-cols-3">
                <ChartCard
                  title="Service success rates"
                  subtitle="Daily share of successful outcomes (%)"
                  className="xl:col-span-2"
                  table={toTable(
                    merge(o.trends, ['delivery_success_rate', 'payment_success_rate', 'refund_completion_rate', 'service_availability']),
                    'date',
                    [
                      { key: 'delivery_success_rate', label: 'Delivery on time' },
                      { key: 'payment_success_rate', label: 'Payment success' },
                      { key: 'refund_completion_rate', label: 'Refund in SLA' },
                      { key: 'service_availability', label: 'Crash-free sessions' },
                    ]
                  )}
                >
                  <TrendChart
                    data={merge(o.trends, ['delivery_success_rate', 'payment_success_rate', 'refund_completion_rate', 'service_availability'])}
                    xFmt={shortDay}
                    yFmt={(v) => `${v.toFixed(0)}%`}
                    domain={[60, 100]}
                    series={[
                      { key: 'delivery_success_rate', label: 'Delivery on time' },
                      { key: 'payment_success_rate', label: 'Payment success' },
                      { key: 'refund_completion_rate', label: 'Refund in SLA' },
                      { key: 'service_availability', label: 'Crash-free sessions' },
                    ]}
                  />
                </ChartCard>
                <ChartCard
                  title="Revenue at risk by issue"
                  subtitle="Estimated, INR (3-month horizon)"
                  table={{ headers: ['Issue', 'Revenue at risk', 'Affected'], rows: o.revenue_by_issue.map((r) => [r.title, inr(r.revenue_at_risk), num(r.affected)]) }}
                >
                  <BarsChart
                    layout="vertical"
                    data={o.revenue_by_issue}
                    xKey="title"
                    series={[{ key: 'revenue_at_risk', label: 'Revenue at risk' }]}
                    height={220}
                    yFmt={(v) => inr(v)}
                    colorByRow={(r) => SEVERITY_COLOR[r.severity]}
                    labelWidth={120}
                  />
                </ChartCard>
              </div>

              {/* Bottom Tables */}
              <div className="grid gap-5 xl:grid-cols-3">
                <Card title="Recent incidents" subtitle="Most recently updated issues" className="xl:col-span-2" pad={false}>
                  <Table>
                    <thead>
                      <tr>
                        <Th>Issue</Th>
                        <Th>Severity</Th>
                        <Th>Status</Th>
                        <Th>Confidence</Th>
                        <Th>Growth</Th>
                        <Th>Onset</Th>
                      </tr>
                    </thead>
                    <tbody>
                      {o.recent_incidents.map((i) => (
                        <tr key={i.id} className="hover:bg-slate-50">
                          <Td>
                            <Link to={`/investigations/${i.id}`} className="font-medium text-brand hover:underline">
                              {i.code}
                            </Link>
                            <div className="max-w-md truncate text-xs text-ink-2">{i.title}</div>
                          </Td>
                          <Td>
                            <SeverityBadge severity={i.severity} />
                          </Td>
                          <Td>
                            <StatusBadge status={i.status} />
                          </Td>
                          <Td className="tnum">{pct(i.detection_confidence)}</Td>
                          <Td className="tnum">
                            {i.growth_rate >= 0 ? '+' : ''}
                            {pct(i.growth_rate)}
                          </Td>
                          <Td>{date(i.onset_at)}</Td>
                        </tr>
                      ))}
                    </tbody>
                  </Table>
                </Card>

                <Card
                  title="Awaiting your decision"
                  subtitle="Consequential actions need human approval"
                  actions={
                    <Link to="/approvals" className="text-xs text-brand hover:underline">
                      All approvals
                    </Link>
                  }
                >
                  {!pend.data?.length ? (
                    <EmptyState
                      title="Nothing pending"
                      hint="Approval requests appear here when agents recommend a consequential action."
                      icon={<ShieldCheck size={18} />}
                    />
                  ) : (
                    <ul className="space-y-3">
                      {pend.data.slice(0, 4).map((a) => (
                        <li key={a.id} className="rounded-lg border border-line p-3">
                          <div className="flex items-center justify-between gap-2">
                            <span className="text-xs font-medium text-muted">
                              {a.issue?.code} · {a.intervention.code}
                            </span>
                            <StatusBadge status="pending" />
                          </div>
                          <p className="mt-1 text-sm font-medium">{a.intervention.title}</p>
                          <p className="mt-0.5 text-xs text-ink-2">
                            Cost {inr(a.intervention.cost_inr)} · expected impact {pct(a.intervention.expected_impact)}
                          </p>
                        </li>
                      ))}
                    </ul>
                  )}
                </Card>
              </div>

              {/* CARD INSPECTOR DRAWER */}
              <Drawer
                open={inspectKey !== null}
                onClose={() => setInspectKey(null)}
                width="max-w-2xl"
                title={
                  inspectKey === 'total_issues'
                    ? 'Card Inspector · Detected Issues'
                    : inspectKey === 'critical_issues'
                    ? 'Card Inspector · Critical Severity Issues'
                    : inspectKey === 'affected_customers'
                    ? 'Card Inspector · Affected Customers'
                    : inspectKey === 'revenue_at_risk'
                    ? 'Card Inspector · Revenue at Risk'
                    : inspectKey === 'active_investigations'
                    ? 'Card Inspector · Active Investigations'
                    : inspectKey === 'pending_approvals'
                    ? 'Card Inspector · Pending Approvals'
                    : 'Card Inspector · Recovery Success Rate'
                }
              >
                {inspectKey && (
                  <div className="space-y-5">
                    {/* 1. Header Highlight Box */}
                    <div className="rounded-xl border border-line bg-slate-50/70 p-4">
                      <div className="flex items-start justify-between">
                        <div>
                          <span className="text-xs font-semibold uppercase tracking-wider text-muted">Current Value</span>
                          <div className="mt-1 text-2xl font-bold text-ink">
                            {inspectKey === 'total_issues' && `${k.total_issues} Confirmed Issues`}
                            {inspectKey === 'critical_issues' && `${k.critical_issues} Critical Issues`}
                            {inspectKey === 'affected_customers' && `${num(k.affected_customers)} Customers`}
                            {inspectKey === 'revenue_at_risk' && inr(k.revenue_at_risk)}
                            {inspectKey === 'active_investigations' && `${k.active_investigations} Active Workspaces`}
                            {inspectKey === 'pending_approvals' && `${k.pending_approvals} Decisions Awaiting Sign-off`}
                            {inspectKey === 'recovery_success' && (k.recovery_success_rate == null ? 'N/A' : pct(k.recovery_success_rate))}
                          </div>
                        </div>
                        <Badge tone="blue">Simulated Clock: {date(o.sim_now)}</Badge>
                      </div>
                    </div>

                    {/* 2. Where This Comes From (Provenance & Origins) */}
                    <Card title="Where Does This Data Come From?" subtitle="Data ingestion pipelines & statistical attribution">
                      <div className="space-y-3 text-sm">
                        <div className="flex items-start gap-3">
                          <Database className="mt-0.5 size-4 shrink-0 text-brand" />
                          <div>
                            <span className="font-semibold text-ink">Upstream Data Sources & Tables:</span>
                            <p className="mt-0.5 text-xs text-ink-2">
                              {inspectKey === 'total_issues' &&
                                'customer_signals (Zendesk, Play Store reviews, Twitter/X feeds) clustered into issue_clusters and saved to detected_issues.'}
                              {inspectKey === 'critical_issues' &&
                                'detected_issues table evaluated with multi-factor scoring against historical baselines and business_impact_estimates.'}
                              {inspectKey === 'affected_customers' &&
                                'customer_signals combined with transactions, telemetry sessions, and customer_segments with k-anonymity privacy safeguards.'}
                              {inspectKey === 'revenue_at_risk' &&
                                'transactions (Average Order Value), customer order frequency, and business_impact_estimates generated by the impact model.'}
                              {inspectKey === 'active_investigations' &&
                                'investigations and root_cause_hypotheses tables orchestrated by LangGraph multi-agent supervisor.'}
                              {inspectKey === 'pending_approvals' &&
                                'approval_requests and interventions tables generated by the Intervention Planning Agent awaiting human sign-off.'}
                              {inspectKey === 'recovery_success' &&
                                'recovery_measurements and agent_execution_history tracking pre-intervention vs. post-intervention cohort recovery.'}
                            </p>
                          </div>
                        </div>

                        <div className="flex items-start gap-3">
                          <Cpu className="mt-0.5 size-4 shrink-0 text-teal" />
                          <div>
                            <span className="font-semibold text-ink">Responsible AI Agent:</span>
                            <p className="mt-0.5 text-xs text-ink-2">
                              {inspectKey === 'total_issues' && 'Emerging Issue Detection Agent (LangGraph Agent #2) + Signal Intelligence Agent.'}
                              {inspectKey === 'critical_issues' && 'Emerging Issue Detection Agent + Business Impact Agent.'}
                              {inspectKey === 'affected_customers' && 'Customer Segmentation Agent (LangGraph Agent #3) using Fisher Exact Test & FDR control.'}
                              {inspectKey === 'revenue_at_risk' && 'Business Impact Agent (LangGraph Agent #5) using forward econometric risk modeling.'}
                              {inspectKey === 'active_investigations' && 'Root Cause Investigation Agent (Agent #4) & Evidence Validator (Agent #4b).'}
                              {inspectKey === 'pending_approvals' && 'Intervention Planning Agent (Agent #6) enforcing enterprise safety thresholds.'}
                              {inspectKey === 'recovery_success' && 'Verification & Learning Agent (Agent #8) using cohort binomial hypothesis testing.'}
                            </p>
                          </div>
                        </div>

                        <div className="flex items-start gap-3">
                          <Calculator className="mt-0.5 size-4 shrink-0 text-amber-600" />
                          <div>
                            <span className="font-semibold text-ink">Calculation Method & Formula:</span>
                            <p className="mt-0.5 text-xs text-ink-2">
                              {inspectKey === 'total_issues' &&
                                'HDBSCAN density clustering on SVD/TF-IDF text embeddings. Poisson burst test confirms complaint volume exceeds 14-day historical baseline.'}
                              {inspectKey === 'critical_issues' &&
                                'Composite score ≥ 75/100: Severity = (0.35 × Affected Customer Radius) + (0.30 × Complaint Growth Rate) + (0.25 × Revenue Exposure) + (0.10 × Churn Velocity).'}
                              {inspectKey === 'affected_customers' &&
                                'Unique customer identifiers with verified service failures across active issues: Total = ∑ (Measured Affected Cohort Size). Demographics with <10 users are suppressed for privacy.'}
                              {inspectKey === 'revenue_at_risk' &&
                                'Formula (3-month horizon): Revenue at Risk = ∑ [ Affected Active Customers × Average Order Value (AOV) × Churn / Order Drop Uplift ].'}
                              {inspectKey === 'active_investigations' &&
                                'Count of detected issues whose status is active: open, investigating, awaiting_approval, or reopened.'}
                              {inspectKey === 'pending_approvals' &&
                                'Active candidate interventions flagged as consequential (Cost > ₹10,000, vendor reassignment, or config change) where approval_status = "pending".'}
                              {inspectKey === 'recovery_success' &&
                                'Two-proportion z-test comparing failure rates: Success Rate = (Recovered Outcomes ÷ Total Decided Cohorts). If p ≥ 0.05, the intervention is deemed not recovered.'}
                            </p>
                          </div>
                        </div>
                      </div>
                    </Card>

                    {/* 3. Detailed Data Breakdown Table */}
                    <Card
                      title={
                        inspectKey === 'revenue_at_risk'
                          ? 'Revenue Exposure Breakdown by Incident'
                          : inspectKey === 'affected_customers'
                          ? 'Affected Customer Distribution by Incident'
                          : inspectKey === 'pending_approvals'
                          ? 'Interventions Awaiting Human Authorization'
                          : 'Contributing Incidents'
                      }
                      subtitle="Live records contributing to this metric"
                      pad={false}
                    >
                      {inspectKey === 'revenue_at_risk' && (
                        <Table>
                          <thead>
                            <tr>
                              <Th>Issue / Code</Th>
                              <Th>Severity</Th>
                              <Th className="text-right">Revenue at Risk</Th>
                              <Th className="text-right">Affected</Th>
                              <Th className="text-right">Share</Th>
                            </tr>
                          </thead>
                          <tbody>
                            {o.revenue_by_issue.map((r, idx) => {
                              const share = k.revenue_at_risk > 0 ? (r.revenue_at_risk / k.revenue_at_risk) * 100 : 0
                              return (
                                <tr key={idx} className="hover:bg-slate-50">
                                  <Td>
                                    <span className="font-semibold text-brand">{r.issue}</span>
                                    <div className="text-xs text-ink-2">{r.title}</div>
                                  </Td>
                                  <Td>
                                    <SeverityBadge severity={r.severity} />
                                  </Td>
                                  <Td className="tnum text-right font-medium">{inr(r.revenue_at_risk)}</Td>
                                  <Td className="tnum text-right text-xs text-ink-2">{num(r.affected)}</Td>
                                  <Td className="tnum text-right text-xs text-muted">{share.toFixed(1)}%</Td>
                                </tr>
                              )
                            })}
                          </tbody>
                        </Table>
                      )}

                      {inspectKey === 'affected_customers' && (
                        <Table>
                          <thead>
                            <tr>
                              <Th>Incident</Th>
                              <Th>Category</Th>
                              <Th>Severity</Th>
                              <Th className="text-right">Affected Cohort</Th>
                              <Th className="text-right">Action</Th>
                            </tr>
                          </thead>
                          <tbody>
                            {o.revenue_by_issue.map((r, idx) => (
                              <tr key={idx} className="hover:bg-slate-50">
                                <Td>
                                  <span className="font-semibold text-ink">{r.issue}</span>
                                </Td>
                                <Td className="text-xs text-ink-2">{r.title}</Td>
                                <Td>
                                  <SeverityBadge severity={r.severity} />
                                </Td>
                                <Td className="tnum text-right font-medium">{num(r.affected)} users</Td>
                                <Td className="text-right">
                                  <Link to="/impact" className="text-xs text-brand hover:underline inline-flex items-center gap-1">
                                    Segments <ArrowRight size={12} />
                                  </Link>
                                </Td>
                              </tr>
                            ))}
                          </tbody>
                        </Table>
                      )}

                      {(inspectKey === 'total_issues' || inspectKey === 'critical_issues' || inspectKey === 'active_investigations') && (
                        <Table>
                          <thead>
                            <tr>
                              <Th>Code</Th>
                              <Th>Title</Th>
                              <Th>Severity</Th>
                              <Th>Status</Th>
                              <Th className="text-right">Action</Th>
                            </tr>
                          </thead>
                          <tbody>
                            {(inspectKey === 'critical_issues' ? criticalIssues : inspectKey === 'active_investigations' ? activeIssues : issuesList).map(
                              (i) => (
                                <tr key={i.id} className="hover:bg-slate-50">
                                  <Td>
                                    <span className="font-semibold text-brand">{i.code}</span>
                                  </Td>
                                  <Td>
                                    <div className="max-w-xs truncate text-xs font-medium text-ink">{i.title}</div>
                                    <div className="text-[11px] text-muted">{date(i.onset_at)}</div>
                                  </Td>
                                  <Td>
                                    <SeverityBadge severity={i.severity} />
                                  </Td>
                                  <Td>
                                    <StatusBadge status={i.status} />
                                  </Td>
                                  <Td className="text-right">
                                    <Link to={`/investigations/${i.id}`} className="text-xs text-brand hover:underline">
                                      Investigate
                                    </Link>
                                  </Td>
                                </tr>
                              )
                            )}
                          </tbody>
                        </Table>
                      )}

                      {inspectKey === 'pending_approvals' && (
                        <div className="p-4 space-y-3">
                          {!pend.data?.length ? (
                            <EmptyState
                              title="No pending approvals"
                              hint="When agents recommend high-impact interventions, they will show up here for authorization."
                            />
                          ) : (
                            pend.data.map((a) => (
                              <div key={a.id} className="rounded-lg border border-line p-3 hover:bg-slate-50">
                                <div className="flex items-center justify-between">
                                  <span className="text-xs font-semibold text-muted">
                                    {a.issue?.code} · {a.intervention.code}
                                  </span>
                                  <StatusBadge status="pending" />
                                </div>
                                <div className="mt-1 font-medium text-sm text-ink">{a.intervention.title}</div>
                                <div className="mt-1 flex items-center gap-4 text-xs text-ink-2">
                                  <span>Cost: <strong>{inr(a.intervention.cost_inr)}</strong></span>
                                  <span>Expected Impact: <strong>{pct(a.intervention.expected_impact)}</strong></span>
                                  <span>Risk: <strong>{a.intervention.business_risk.toFixed(2)}</strong></span>
                                </div>
                              </div>
                            ))
                          )}
                        </div>
                      )}

                      {inspectKey === 'recovery_success' && (
                        <div className="p-4 space-y-3 text-sm text-ink-2">
                          <p>
                            The <strong>Verification & Learning Agent</strong> conducts automated post-intervention monitoring:
                          </p>
                          <ul className="list-disc pl-5 space-y-1.5 text-xs">
                            <li>Compares daily service metrics of the post-intervention customer cohort against the pre-intervention cohort.</li>
                            <li>Applies a two-proportion binomial z-test on service failure rates.</li>
                            <li>If recovery fails, the agent marks the intervention as <code>not_recovered</code>, down-weights the failed hypothesis, and re-opens the investigation automatically.</li>
                          </ul>
                        </div>
                      )}
                    </Card>

                    {/* 4. Deep-dive Action Button */}
                    <div className="flex justify-end pt-2">
                      {inspectKey === 'total_issues' && (
                        <Link to="/issues">
                          <Button variant="primary" icon={<ExternalLink size={14} />}>
                            Open Issue Intelligence
                          </Button>
                        </Link>
                      )}
                      {inspectKey === 'critical_issues' && (
                        <Link to="/issues">
                          <Button variant="danger" icon={<ExternalLink size={14} />}>
                            View Critical Incidents
                          </Button>
                        </Link>
                      )}
                      {inspectKey === 'affected_customers' && (
                        <Link to="/impact">
                          <Button variant="teal" icon={<ExternalLink size={14} />}>
                            Open Customer Impact & Segments
                          </Button>
                        </Link>
                      )}
                      {inspectKey === 'revenue_at_risk' && (
                        <Link to="/impact">
                          <Button variant="primary" icon={<ExternalLink size={14} />}>
                            View Detailed Financial Models
                          </Button>
                        </Link>
                      )}
                      {inspectKey === 'active_investigations' && (
                        <Link to="/investigations">
                          <Button variant="primary" icon={<ExternalLink size={14} />}>
                            Open Root Cause & Evidence Graph
                          </Button>
                        </Link>
                      )}
                      {inspectKey === 'pending_approvals' && (
                        <Link to="/approvals">
                          <Button variant="primary" icon={<ExternalLink size={14} />}>
                            Go to Approval Center
                          </Button>
                        </Link>
                      )}
                      {inspectKey === 'recovery_success' && (
                        <Link to="/monitoring">
                          <Button variant="primary" icon={<ExternalLink size={14} />}>
                            View Recovery Monitoring
                          </Button>
                        </Link>
                      )}
                    </div>
                  </div>
                )}
              </Drawer>
            </div>
          )
        }}
      </Async>
    </>
  )
}
