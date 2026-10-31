import { useState, type ReactNode } from 'react'
import { Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, Legend, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { Table2, BarChart3 } from 'lucide-react'
import { Card, Table, Td, Th, cn } from './ui'

/** Categorical slots in fixed order (validated reference palette). Colour follows the entity, never its rank. */
export const SERIES = ['#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4', '#008300', '#6250d6', '#e34948']
export const SEVERITY_COLOR: Record<string, string> = { critical: '#d03b3b', high: '#ec835a', medium: '#fab219', low: '#1baf7a' }
const GRID = '#e1e0d9'
const AXIS = '#c3c2b7'

export interface SeriesDef { key: string; label: string; color?: string; dashed?: boolean }
type Row = Record<string, any>

function TooltipBox({ active, payload, label, fmt, labelFmt }: any) {
  if (!active || !payload?.length) return null
  return (
    <div className="rounded-lg border border-line bg-white px-3 py-2 text-xs shadow-lg">
      <div className="mb-1 font-medium text-ink">{labelFmt ? labelFmt(label) : label}</div>
      {payload.map((p: any) => (
        <div key={p.dataKey} className="flex items-center justify-between gap-4 py-0.5">
          <span className="flex items-center gap-1.5 text-ink-2"><span className="size-2 rounded-full" style={{ background: p.color ?? p.fill }} />{p.name}</span>
          <span className="tnum font-medium text-ink">{fmt ? fmt(p.value) : p.value}</span>
        </div>
      ))}
    </div>
  )
}

/** Card with a chart / table toggle so the same data is always available as text. */
export function ChartCard({ title, subtitle, children, table, actions, className }: { title: string; subtitle?: string; children: ReactNode; table?: { headers: string[]; rows: ReactNode[][] }; actions?: ReactNode; className?: string }) {
  const [view, setView] = useState<'chart' | 'table'>('chart')
  return (
    <Card title={title} subtitle={subtitle} className={className}
      actions={<>{actions}{table && (
        <button onClick={() => setView(view === 'chart' ? 'table' : 'chart')} aria-label={view === 'chart' ? 'Show table view' : 'Show chart view'}
          className="rounded-md p-1.5 text-muted hover:bg-slate-100 hover:text-ink">{view === 'chart' ? <Table2 size={15} /> : <BarChart3 size={15} />}</button>)}</>}>
      {view === 'chart' || !table ? children : (
        <div className="max-h-64 overflow-y-auto">
          <Table><thead><tr>{table.headers.map((h) => <Th key={h}>{h}</Th>)}</tr></thead>
            <tbody>{table.rows.map((r, i) => <tr key={i}>{r.map((c, j) => <Td key={j} className={cn(j > 0 && 'tnum')}>{c}</Td>)}</tr>)}</tbody></Table>
        </div>
      )}
    </Card>
  )
}

export function toTable(data: Row[], xKey: string, series: SeriesDef[], fmt?: (v: number) => string) {
  return { headers: [xKey === 'date' ? 'Date' : xKey, ...series.map((s) => s.label)], rows: data.map((d) => [d[xKey], ...series.map((s) => (d[s.key] == null ? '-' : fmt ? fmt(d[s.key]) : d[s.key]))]) }
}

interface TrendProps {
  data: Row[]; xKey?: string; series: SeriesDef[]; height?: number; yFmt?: (v: number) => string; xFmt?: (v: any) => string
  baseline?: number | null; baselineLabel?: string; markers?: { x: string; label: string; color?: string }[]; domain?: [number | 'auto', number | 'auto']; area?: boolean
}
export function TrendChart({ data, xKey = 'date', series, height = 220, yFmt, xFmt, baseline, baselineLabel = 'Baseline', markers = [], domain, area }: TrendProps) {
  const Chart: any = area ? AreaChart : LineChart
  return (
    <div style={{ height }} role="img" aria-label={`Trend chart of ${series.map((s) => s.label).join(', ')}`}>
      <ResponsiveContainer width="100%" height="100%">
        <Chart data={data} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
          <CartesianGrid stroke={GRID} strokeDasharray="0" vertical={false} />
          <XAxis dataKey={xKey} tick={{ fill: '#7a8799' }} tickFormatter={xFmt} axisLine={{ stroke: AXIS }} tickLine={false} minTickGap={28} />
          <YAxis tick={{ fill: '#7a8799' }} tickFormatter={yFmt} axisLine={false} tickLine={false} width={46} domain={domain ?? ['auto', 'auto']} />
          <Tooltip content={<TooltipBox fmt={yFmt} labelFmt={xFmt} />} cursor={{ stroke: AXIS }} />
          {series.length > 1 && <Legend verticalAlign="top" align="right" height={26} iconType="plainline" wrapperStyle={{ fontSize: 12, color: '#52514e' }} />}
          {baseline != null && <ReferenceLine y={baseline} stroke="#898781" strokeDasharray="4 4" label={{ value: baselineLabel, position: 'insideTopLeft', fill: '#898781', fontSize: 10 }} />}
          {markers.map((m) => <ReferenceLine key={m.x + m.label} x={m.x} stroke={m.color ?? '#0b1f3a'} strokeDasharray="3 3" label={{ value: m.label, position: 'top', fill: m.color ?? '#0b1f3a', fontSize: 10 }} />)}
          {series.map((s, i) => area
            ? <Area key={s.key} type="monotone" dataKey={s.key} name={s.label} stroke={s.color ?? SERIES[i]} fill={s.color ?? SERIES[i]} fillOpacity={0.12} strokeWidth={2} dot={false} />
            : <Line key={s.key} type="monotone" dataKey={s.key} name={s.label} stroke={s.color ?? SERIES[i]} strokeWidth={2} strokeDasharray={s.dashed ? '5 4' : undefined} dot={false} activeDot={{ r: 4, stroke: '#fff', strokeWidth: 2 }} connectNulls />)}
        </Chart>
      </ResponsiveContainer>
    </div>
  )
}

interface BarProps {
  data: Row[]; xKey: string; series: SeriesDef[]; height?: number; layout?: 'horizontal' | 'vertical'; stacked?: boolean; yFmt?: (v: number) => string
  colorByRow?: (row: Row) => string | undefined; labelWidth?: number
}
export function BarsChart({ data, xKey, series, height = 240, layout = 'horizontal', stacked, yFmt, colorByRow, labelWidth = 110 }: BarProps) {
  const vertical = layout === 'vertical'
  return (
    <div style={{ height }} role="img" aria-label={`Bar chart of ${series.map((s) => s.label).join(', ')} by ${xKey}`}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} layout={layout} margin={{ top: 8, right: 16, bottom: 0, left: 0 }} barCategoryGap={vertical ? '28%' : '24%'}>
          <CartesianGrid stroke={GRID} horizontal={!vertical} vertical={vertical} />
          {vertical
            ? <><XAxis type="number" domain={stacked ? ['auto', 'auto'] : [0, 'auto']} tick={{ fill: '#7a8799' }} tickFormatter={yFmt} axisLine={false} tickLine={false} /><YAxis type="category" dataKey={xKey} tick={{ fill: '#52514e' }} width={labelWidth} axisLine={{ stroke: AXIS }} tickLine={false} /></>
            : <><XAxis dataKey={xKey} tick={{ fill: '#7a8799' }} axisLine={{ stroke: AXIS }} tickLine={false} interval={0} /><YAxis tick={{ fill: '#7a8799' }} tickFormatter={yFmt} axisLine={false} tickLine={false} width={46} /></>}
          <Tooltip content={<TooltipBox fmt={yFmt} />} cursor={{ fill: 'rgba(11,31,58,0.04)' }} />
          {series.length > 1 && <Legend verticalAlign="top" align="right" height={26} iconType="circle" iconSize={8} wrapperStyle={{ fontSize: 12, color: '#52514e' }} />}
          {series.map((s, i) => (
            <Bar key={s.key} dataKey={s.key} name={s.label} fill={s.color ?? SERIES[i]} stackId={stacked ? 'a' : undefined} maxBarSize={vertical ? 18 : 34} stroke={stacked ? '#fff' : undefined} strokeWidth={stacked ? 2 : 0}
              radius={stacked ? 0 : vertical ? [0, 4, 4, 0] : [4, 4, 0, 0]}>
              {colorByRow && series.length === 1 && data.map((r, j) => <Cell key={j} fill={colorByRow(r) ?? s.color ?? SERIES[i]} />)}
            </Bar>
          ))}
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

export function Sparkline({ values, color = SERIES[0], width = 84, height = 26 }: { values: number[]; color?: string; width?: number; height?: number }) {
  if (!values?.length) return <span className="text-xs text-muted">-</span>
  const max = Math.max(...values, 1)
  const pts = values.map((v, i) => `${(i / Math.max(values.length - 1, 1)) * width},${height - 2 - (v / max) * (height - 4)}`).join(' ')
  return <svg width={width} height={height} aria-hidden><polyline points={pts} fill="none" stroke={color} strokeWidth={1.8} strokeLinejoin="round" strokeLinecap="round" /></svg>
}
