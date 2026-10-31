import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { get } from '@/lib/api'
import { inr, num, pct, title } from '@/lib/format'
import type { ImpactEstimate, Investigation, Issue } from '@/lib/types'
import { Async, Banner, Card, Disclosure, EmptyState, Field, inputCls, KindBadge, PageHeader, SeverityBadge, Table, Td, Th } from '@/components/ui'
import { BarsChart, ChartCard, SEVERITY_COLOR, SERIES } from '@/components/charts'

const fmtVal = (e: ImpactEstimate, v: number | null) => {
  if (v == null) return '-'
  if (e.unit === 'INR') return inr(v)
  if (e.unit === 'ratio' || e.unit === 'rate' || e.unit === 'probability') return pct(v, 1)
  if (e.unit === '0-100') return v.toFixed(0)
  return num(v)
}

function IssueImpact({ id }: { id: number }) {
  const q = useQuery({ queryKey: ['investigation', id], queryFn: () => get<Investigation>(`/investigations/${id}`) })
  return (
    <Async q={q}>
      {(inv) => {
        const seg = inv.segmentation
        const est = Object.fromEntries(inv.impact.map((e) => [e.metric, e]))
        return (
          <div className="space-y-5">
            <Card title="Impact estimates" subtitle="Every value shows whether it is measured or estimated, its formula, inputs, assumptions and uncertainty range" pad={false}>
              <Table>
                <thead><tr><Th>Metric</Th><Th>Value</Th><Th>Range (95%)</Th><Th>Type</Th><Th>Calculated</Th></tr></thead>
                <tbody>
                  {inv.impact.map((e) => (
                    <tr key={e.metric} className="align-top">
                      <Td className="w-[38%]">
                        <Disclosure summary={<span className="font-medium">{e.label}</span>}>
                          <div className="space-y-2 rounded-lg bg-slate-50 p-3 text-xs text-ink-2">
                            <p><span className="font-semibold text-ink">Formula</span><br />{e.formula}</p>
                            <p><span className="font-semibold text-ink">Inputs</span></p>
                            <pre className="overflow-auto rounded bg-white p-2 text-[11px] ring-1 ring-line">{JSON.stringify(e.inputs, null, 2)}</pre>
                            <p className="font-semibold text-ink">Assumptions</p>
                            <ul className="list-disc space-y-0.5 pl-4">{e.assumptions?.map((a) => <li key={a}>{a}</li>)}</ul>
                          </div>
                        </Disclosure>
                      </Td>
                      <Td className="tnum text-base font-semibold">{fmtVal(e, e.value)}</Td>
                      <Td className="tnum text-xs text-ink-2">{e.ci_low != null ? `${fmtVal(e, e.ci_low)} – ${fmtVal(e, e.ci_high)}` : <span className="text-muted">exact / n.a.</span>}</Td>
                      <Td><KindBadge kind={e.kind} /></Td>
                      <Td className="whitespace-nowrap text-xs text-muted">{new Date(e.calculated_at).toLocaleString('en-GB', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' })}</Td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            </Card>
            {seg && (
              <div className="grid gap-5 xl:grid-cols-2">
                <ChartCard title="Affected rate by customer segment" subtitle="Share of each predefined segment that is affected" table={{ headers: ['Segment', 'Customers', 'Affected', 'Rate', 'Revenue exposure (30d)'], rows: seg.predefined.map((s) => [s.name ?? s.value, s.customers, s.affected, pct(s.rate, 1), inr(s.revenue_exposure_30d)]) }}>
                  <BarsChart layout="vertical" height={Math.max(180, seg.predefined.length * 46)} labelWidth={150} data={seg.predefined.map((s) => ({ name: s.name ?? s.value, rate: Number((s.rate * 100).toFixed(1)), severity: s.severity }))} xKey="name" series={[{ key: 'rate', label: 'Affected %' }]} yFmt={(v) => `${v}%`} colorByRow={(r) => SEVERITY_COLOR[r.severity]} />
                </ChartCard>
                <ChartCard title="Geographic impact" subtitle="Share of customers affected by city" table={{ headers: ['City', 'Customers', 'Affected', 'Rate', 'Revenue exposure (30d)'], rows: seg.geography.map((s) => [s.value, s.customers, s.affected, pct(s.rate, 1), inr(s.revenue_exposure_30d)]) }}>
                  <BarsChart layout="vertical" height={Math.max(180, seg.geography.length * 40)} labelWidth={90} data={seg.geography.map((s) => ({ name: s.value, rate: Number((s.rate * 100).toFixed(1)), severity: s.severity }))} xKey="name" series={[{ key: 'rate', label: 'Affected %' }]} yFmt={(v) => `${v}%`} colorByRow={(r) => SEVERITY_COLOR[r.severity]} />
                </ChartCard>
                <Card title="Customer risk and revenue exposure" subtitle="Which customers carry the most revenue at stake">
                  <dl className="divide-y divide-line-2 text-sm">
                    <div className="flex justify-between py-2"><dt className="text-ink-2">Monthly revenue of affected customers</dt><dd className="font-semibold">{inr(seg.revenue_exposure_30d)}</dd></div>
                    <div className="flex justify-between py-2"><dt className="text-ink-2">Churn probability (affected)</dt><dd className="font-semibold">{est.retention_risk ? fmtVal(est.retention_risk, est.retention_risk.value) : '-'}</dd></div>
                    <div className="flex justify-between py-2"><dt className="text-ink-2">Revenue at risk (3 months)</dt><dd className="font-semibold">{est.revenue_at_risk ? inr(est.revenue_at_risk.value) : '-'}</dd></div>
                    <div className="flex justify-between py-2"><dt className="text-ink-2">Business severity score</dt><dd className="font-semibold">{est.business_severity_score ? est.business_severity_score.value?.toFixed(0) : '-'}</dd></div>
                  </dl>
                </Card>
                <ChartCard title="Product-level impact" subtitle="Failure events by product category since onset" table={{ headers: ['Category', 'Events'], rows: seg.products.map((p) => [p.value, p.bad_events]) }}>
                  {seg.products.length ? <BarsChart layout="vertical" height={Math.max(180, seg.products.length * 40)} labelWidth={130} data={seg.products.map((p) => ({ name: p.value, events: p.bad_events }))} xKey="name" series={[{ key: 'events', label: 'Failure events', color: SERIES[2] }]} /> : <EmptyState title="No product-level breakdown for this issue" />}
                </ChartCard>
              </div>
            )}
            {seg && <Banner tone="blue">{seg.privacy_notes[0]} {seg.suppressed_groups} group(s) were suppressed. Segment analysis never uses protected attributes.</Banner>}
          </div>
        )
      }}
    </Async>
  )
}

export default function Impact() {
  const [issueId, setIssueId] = useState<number | null>(null)
  const ov = useQuery({ queryKey: ['impact-overview'], queryFn: () => get<any>('/impact/overview') })
  const issues = useQuery({ queryKey: ['issues'], queryFn: () => get<Issue[]>('/issues') })
  const sel = issueId ?? issues.data?.find((i) => i.status !== 'watchlist')?.id ?? null
  return (
    <>
      <PageHeader title="Customer Impact Analysis" description="Who is affected, where, how much revenue is exposed and how confident we are. Measured facts and modelled estimates are always labelled separately."
        actions={issues.data && <Field label="Issue"><select className={`${inputCls} w-72`} value={sel ?? ''} onChange={(e) => setIssueId(Number(e.target.value))}>{issues.data.filter((i) => i.status !== 'watchlist').map((i) => <option key={i.id} value={i.id}>{i.code} · {i.category}</option>)}</select></Field>} />
      <Async q={ov}>
        {(o) => (
          <div className="mb-5 grid gap-5 xl:grid-cols-3">
            <ChartCard title="Revenue at risk by issue" subtitle="Estimated, 3-month horizon" table={{ headers: ['Issue', 'Revenue at risk', 'Affected', 'Next 7d'], rows: o.issues.map((r: any) => [r.category, inr(r.revenue_at_risk), num(r.affected), num(r.next_7d)]) }}>
              <BarsChart layout="vertical" height={230} labelWidth={130} data={o.issues} xKey="category" series={[{ key: 'revenue_at_risk', label: 'Revenue at risk' }]} yFmt={(v) => inr(v)} colorByRow={(r) => SEVERITY_COLOR[r.severity]} />
            </ChartCard>
            <ChartCard title="Impact comparison" subtitle="Measured affected customers vs expected next 7 days" table={{ headers: ['Issue', 'Affected', 'Next 7 days'], rows: o.issues.map((r: any) => [r.category, num(r.affected), num(r.next_7d)]) }}>
              <BarsChart height={230} data={o.issues.map((r: any) => ({ name: r.code, affected: Math.round(r.affected), next_7d: Math.round(r.next_7d) }))} xKey="name" series={[{ key: 'affected', label: 'Measured affected' }, { key: 'next_7d', label: 'Expected next 7 days' }]} />
            </ChartCard>
            <ChartCard title="Affected customers by city" subtitle="Distinct customers per issue" table={{ headers: ['City', 'Customers', 'Revenue exposure'], rows: o.geography.map((g: any) => [g.city, g.customers, inr(g.revenue_exposure_30d)]) }}>
              <BarsChart stacked height={230} data={o.geography} xKey="city" series={[{ key: 'delivery', label: 'Delivery' }, { key: 'payment', label: 'Payment' }, { key: 'app', label: 'App' }, { key: 'product_quality', label: 'Quality' }, { key: 'refund', label: 'Refund' }]} />
            </ChartCard>
          </div>
        )}
      </Async>
      {sel ? (
        <>
          <div className="mb-3 flex items-center gap-2"><h2 className="text-base font-semibold">Detail</h2>{issues.data?.filter((i) => i.id === sel).map((i) => <span key={i.id} className="flex items-center gap-2 text-sm text-ink-2"><SeverityBadge severity={i.severity} />{title(i.title)}</span>)}</div>
          <IssueImpact id={sel} />
        </>
      ) : <Card><EmptyState title="No issue selected" /></Card>}
    </>
  )
}
