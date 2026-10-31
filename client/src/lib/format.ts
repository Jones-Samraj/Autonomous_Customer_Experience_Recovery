export const num = (v: number | null | undefined, d = 0) =>
  v == null || Number.isNaN(v) ? '-' : v.toLocaleString('en-IN', { maximumFractionDigits: d, minimumFractionDigits: d })

export const inr = (v: number | null | undefined) => {
  if (v == null || Number.isNaN(v)) return '-'
  const a = Math.abs(v)
  if (a >= 1e7) return `₹${(v / 1e7).toFixed(2)} Cr`
  if (a >= 1e5) return `₹${(v / 1e5).toFixed(2)} L`
  return `₹${Math.round(v).toLocaleString('en-IN')}`
}

export const pct = (v: number | null | undefined, d = 0) => (v == null || Number.isNaN(v) ? '-' : `${(v * 100).toFixed(d)}%`)

export const date = (s: string | null | undefined, withTime = false) => {
  if (!s) return '-'
  const d = new Date(s)
  if (Number.isNaN(d.getTime())) return s
  return d.toLocaleString('en-GB', withTime ? { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' } : { day: '2-digit', month: 'short', year: 'numeric' })
}

export const shortDay = (s: string) => {
  const d = new Date(s)
  return d.toLocaleDateString('en-GB', { day: '2-digit', month: 'short' })
}

export const title = (s: string | null | undefined) => (s ?? '').replace(/_/g, ' ').replace(/^\w/, (c) => c.toUpperCase())

export const CRITERIA_LABEL: Record<string, string> = {
  expected_impact: 'Expected impact', customer_benefit: 'Customer benefit', confidence: 'Confidence', feasibility: 'Feasibility',
  reversibility: 'Reversibility', business_risk: 'Business risk', cost: 'Cost', execution_time: 'Execution time',
}

export const KPI_FMT: Record<string, (v: number) => string> = {
  late_delivery_rate: (v) => pct(v, 1), payment_failure_rate: (v) => pct(v, 1), crash_rate: (v) => pct(v, 2), defect_return_rate: (v) => pct(v, 1), refund_sla_breach_rate: (v) => pct(v, 1),
}
