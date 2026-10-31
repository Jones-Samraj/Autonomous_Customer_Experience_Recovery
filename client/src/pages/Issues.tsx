import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowUpRight, Radar } from 'lucide-react'
import { get, post } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import { CRITERIA_LABEL, KPI_FMT, date, pct, shortDay, title } from '@/lib/format'
import type { Issue } from '@/lib/types'
import { Async, Badge, Button, Card, Drawer, EmptyState, KV, Meter, PageHeader, SeverityBadge, StatusBadge, Table, Td, Th } from '@/components/ui'
import { BarsChart, ChartCard, SEVERITY_COLOR, Sparkline, TrendChart } from '@/components/charts'
import { toast } from '@/components/toast'

function Detail({ id }: { id: number }) {
  const q = useQuery({ queryKey: ['issue', id], queryFn: () => get<Issue & { clusters: any[]; evidence_count: number }>(`/issues/${id}`) })
  const ev = useQuery({ queryKey: ['issue-evidence', id], queryFn: () => get<any>(`/issues/${id}/evidence`, { size: 8 }) })
  return (
    <Async q={q}>
      {(i) => {
        const fmt = KPI_FMT[i.kpi_name ?? ''] ?? ((v: number) => v.toFixed(3))
        const counts = Object.entries(i.stats?.daily_counts ?? {}).map(([d, c]) => ({ date: d, complaints: c as number }))
        const onset = i.onset_at?.slice(0, 10)
        return (
          <div className="space-y-5">
            <div className="flex flex-wrap items-center gap-2"><SeverityBadge severity={i.severity} /><StatusBadge status={i.status} /><Badge tone="neutral">Iteration {i.iteration}</Badge>{i.reopen_count > 0 && <Badge tone="red">Re-opened ×{i.reopen_count}</Badge>}</div>
            <p className="text-sm text-ink-2">{i.description}</p>
            {i.kpi_series && i.kpi_series.length > 0 && (
              <ChartCard title={`${title(i.kpi_name)} by day`} subtitle="Cohort rate with historical baseline and detected onset" table={{ headers: ['Date', 'Rate', 'Events', 'Units'], rows: i.kpi_series.map((r) => [r.date, fmt(r.rate), r.k, r.n]) }}>
                <TrendChart data={i.kpi_series} xFmt={shortDay} yFmt={(v) => fmt(v)} series={[{ key: 'rate', label: title(i.kpi_name) }]} baseline={i.baseline_rate} markers={onset ? [{ x: onset, label: 'onset', color: '#d03b3b' }] : []} />
              </ChartCard>
            )}
            <ChartCard title="Complaint volume" subtitle="Clustered negative signals about this issue" table={{ headers: ['Date', 'Complaints'], rows: counts.map((c) => [c.date, c.complaints]) }}>
              <TrendChart data={counts} xFmt={shortDay} series={[{ key: 'complaints', label: 'Complaints per day', color: '#1baf7a' }]} baseline={i.stats?.text?.baseline_mean} baselineLabel="Baseline mean" area />
            </ChartCard>
            <div className="grid gap-4 md:grid-cols-2">
              <Card title="Detection facts">
                <dl className="divide-y divide-line-2"><KV k="First detectable" v={date(i.first_detected_at)} /><KV k="Anomaly onset" v={date(i.onset_at)} /><KV k="Supporting signals" v={i.support_count} /><KV k="Duplicate reports removed" v={i.duplicate_count} />
                  <KV k="Detection confidence" v={pct(i.detection_confidence)} /><KV k="Complaint growth" v={`${pct(i.growth_rate)} vs baseline`} /><KV k="Embedding backend" v={i.stats?.embedding_backend} />
                  {i.stats?.isolation_forest && <KV k="Multivariate anomaly (IsolationForest)" v={`${i.stats.isolation_forest.flagged_days} of ${i.stats.isolation_forest.recent_days} recent days`} />}</dl>
              </Card>
              <Card title="Severity breakdown" subtitle={`Score ${i.severity_score.toFixed(0)} / 100`}>
                <BarsChart layout="vertical" height={190} labelWidth={118} data={Object.entries(i.severity_breakdown?.components ?? {}).map(([k, v]) => ({ k: CRITERIA_LABEL[k] ?? title(k), v: Number((v * 100).toFixed(0)) }))} xKey="k" series={[{ key: 'v', label: 'Component (0-100)' }]} yFmt={(v) => `${v}`} />
              </Card>
            </div>
            <Card title="Semantic clusters" subtitle="HDBSCAN on text embeddings, tested against the baseline" pad={false}>
              <Table><thead><tr><Th>Cluster</Th><Th>Size</Th><Th>Recent / expected</Th><Th>z</Th><Th>Flags</Th></tr></thead>
                <tbody>{i.clusters.map((c) => <tr key={c.id}><Td className="max-w-xs"><div className="truncate font-medium">{c.label}</div></Td><Td className="tnum">{c.size}</Td><Td className="tnum">{c.recent_count} / {c.expected?.toFixed(1)}</Td><Td className="tnum">{c.z?.toFixed(1)}</Td>
                  <Td>{c.is_new && <Badge tone="violet">New category</Badge>} {c.is_anomalous && <Badge tone="red">Anomalous</Badge>}</Td></tr>)}</tbody></Table>
            </Card>
            <Card title="Evidence references" subtitle={`${i.evidence_count} linked records`} pad={false}>
              <Async q={ev}>{(e) => <ul className="divide-y divide-line-2">{e.items.map((s: any) => <li key={s.id} className="px-5 py-2.5 text-sm"><div className="flex items-center gap-2 text-xs text-muted"><Badge>{title(s.source_type)}</Badge>{date(s.occurred_at, true)}{s.is_duplicate && <Badge tone="amber">duplicate</Badge>}</div><p className="mt-1 line-clamp-2">{s.text ?? `${title(s.metric_name)} ${s.numeric_value}`}</p></li>)}</ul>}</Async>
            </Card>
            <Link to={`/investigations/${i.id}`}><Button variant="primary" icon={<ArrowUpRight size={15} />}>Open root-cause investigation</Button></Link>
          </div>
        )
      }}
    </Async>
  )
}

export default function Issues() {
  const { can } = useAuth()
  const qc = useQueryClient()
  const [sel, setSel] = useState<Issue | null>(null)
  const q = useQuery({ queryKey: ['issues'], queryFn: () => get<Issue[]>('/issues') })
  const detect = useMutation({ mutationFn: () => post('/issues/detect'), onSuccess: (r: any) => { toast.success(`Detection finished: ${r.issues.length} issue(s) confirmed`); qc.invalidateQueries() }, onError: toast.error })
  return (
    <>
      <PageHeader title="Issue Intelligence" description="Emerging problems found by clustering complaints and testing them against historical baselines. Decoys and one-day bursts stay on the watchlist instead of becoming false alarms."
        actions={can('analyst') && <Button variant="primary" icon={<Radar size={15} />} loading={detect.isPending} onClick={() => detect.mutate()}>Run detection</Button>} />
      <Async q={q}>
        {(issues) => !issues.length ? <Card><EmptyState title="No issues yet" hint="Run detection once evidence is loaded." /></Card> : (
          <div className="space-y-5">
            <ChartCard title="Severity ranking" subtitle="Explainable severity score (0-100)" table={{ headers: ['Issue', 'Severity score'], rows: issues.map((i) => [i.title, i.severity_score.toFixed(0)]) }}>
              <BarsChart layout="vertical" data={issues.map((i) => ({ name: i.category, score: Math.round(i.severity_score), severity: i.severity }))} xKey="name" series={[{ key: 'score', label: 'Severity score' }]} height={Math.max(160, issues.length * 44)} colorByRow={(r) => SEVERITY_COLOR[r.severity]} labelWidth={150} />
            </ChartCard>
            <Card pad={false}>
              <Table>
                <thead><tr><Th>Issue</Th><Th>Category</Th><Th>Severity</Th><Th>Trend (complaints)</Th><Th>Growth</Th><Th>Evidence</Th><Th>Confidence</Th><Th>First detected</Th><Th>Status</Th></tr></thead>
                <tbody>
                  {issues.map((i) => (
                    <tr key={i.id} className="cursor-pointer hover:bg-slate-50" onClick={() => setSel(i)}>
                      <Td><div className="font-medium text-brand">{i.code}</div><div className="max-w-sm truncate text-xs text-ink-2">{i.title}</div></Td>
                      <Td>{i.category}<div className="text-[11px] text-muted">{i.clusters} clusters</div></Td>
                      <Td><SeverityBadge severity={i.severity} /><div className="tnum mt-0.5 text-[11px] text-muted">score {i.severity_score.toFixed(0)}</div></Td>
                      <Td><Sparkline values={i.sparkline ?? []} color={SEVERITY_COLOR[i.severity]} /></Td>
                      <Td className="tnum">{i.growth_rate >= 0 ? '+' : ''}{pct(i.growth_rate)}</Td>
                      <Td className="tnum">{i.support_count}<div className="text-[11px] text-muted">{i.duplicate_count} dupes</div></Td>
                      <Td className="w-32"><Meter value={i.detection_confidence} /></Td>
                      <Td className="whitespace-nowrap text-xs text-ink-2">{date(i.first_detected_at)}</Td>
                      <Td><StatusBadge status={i.status} /></Td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            </Card>
          </div>
        )}
      </Async>
      <Drawer open={!!sel} onClose={() => setSel(null)} title={sel ? `${sel.code} · ${sel.category}` : ''} width="max-w-3xl">{sel && <Detail id={sel.id} />}</Drawer>
    </>
  )
}
