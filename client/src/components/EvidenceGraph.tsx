import { useMemo, useState } from 'react'
import { Background, Controls, Handle, MarkerType, Position, ReactFlow, type Edge, type Node, type NodeProps } from '@xyflow/react'
import { AlertOctagon, BarChart3, FileText, Lightbulb, MessageSquareText, Rocket, Rocket as Tool, Tag, Users, Activity } from 'lucide-react'
import { pct, title } from '@/lib/format'
import { Badge, cn } from './ui'

interface GNodeData { type: string; label: string; meta?: string; selected?: boolean; [k: string]: unknown }
const STYLE: Record<string, { color: string; icon: any; name: string }> = {
  issue: { color: '#d03b3b', icon: AlertOctagon, name: 'Issue' },
  hypothesis: { color: '#2a78d6', icon: Lightbulb, name: 'Hypothesis' },
  signal_group: { color: '#1baf7a', icon: MessageSquareText, name: 'Signals' },
  segment: { color: '#6250d6', icon: Users, name: 'Segment' },
  event: { color: '#eb6834', icon: Tag, name: 'Operational event' },
  release: { color: '#eda100', icon: Rocket, name: 'Release' },
  metric: { color: '#0f9d8a', icon: Activity, name: 'Metric' },
  statistic: { color: '#52514e', icon: BarChart3, name: 'Statistic' },
  intervention: { color: '#e87ba4', icon: Tool, name: 'Intervention' },
}
const COL: Record<string, number> = { signal_group: 0, event: 0, release: 0, metric: 0, statistic: 0, hypothesis: 1, issue: 2, segment: 3, intervention: 2 }
const EDGE: Record<string, { color: string; dash?: string; label: string }> = {
  supports: { color: '#1baf7a', label: 'supports' }, contradicts: { color: '#d03b3b', dash: '6 4', label: 'contradicts' }, explains: { color: '#2a78d6', label: 'explains' },
  reports: { color: '#898781', label: 'reports' }, concentrated_in: { color: '#6250d6', dash: '2 3', label: 'concentrated in' }, addresses: { color: '#e87ba4', dash: '8 3 2 3', label: 'addresses' },
}

function GNode({ data }: NodeProps<Node<GNodeData>>) {
  const s = STYLE[data.type] ?? STYLE.statistic
  const Icon = s.icon
  return (
    <div className={cn('w-60 rounded-lg border bg-white px-3 py-2 shadow-card', data.selected ? 'border-brand ring-2 ring-brand/25' : 'border-line')} style={{ borderLeft: `4px solid ${s.color}` }}>
      <Handle type="target" position={Position.Left} className="!bg-slate-300" />
      <div className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wide" style={{ color: s.color }}><Icon size={12} />{s.name}</div>
      <div className="mt-0.5 text-[13px] font-medium leading-snug text-ink">{data.label}</div>
      {data.meta && <div className="mt-0.5 text-[11px] text-ink-2">{data.meta}</div>}
      <Handle type="source" position={Position.Right} className="!bg-slate-300" />
    </div>
  )
}
const nodeTypes = { g: GNode }

export default function EvidenceGraph({ graph }: { graph: { nodes: any[]; edges: any[] } }) {
  const [sel, setSel] = useState<string | null>(null)
  const { nodes, edges } = useMemo(() => {
    const GAP = 100
    const pos: Record<string, { x: number; y: number }> = {}
    const byId: Record<string, any> = Object.fromEntries(graph.nodes.map((n) => [n.id, n]))
    const hyps = graph.nodes.filter((n) => n.type === 'hypothesis')
    // each hypothesis gets a block: its evidence stacked on the left, the hypothesis vertically centred beside them
    const placed = new Set<string>()
    let y = 0
    hyps.forEach((h) => {
      const ev = graph.edges.filter((e) => e.target === h.id && (COL[byId[e.source]?.type] ?? 9) === 0 && !placed.has(e.source)).map((e) => e.source)
      ev.forEach((id, i) => { pos[id] = { x: 0, y: y + i * GAP }; placed.add(id) })
      const h_ = Math.max(1, ev.length) * GAP
      pos[h.id] = { x: 400, y: y + (h_ - GAP) / 2 }
      y += h_ + 28
    })
    const mid = Math.max(0, (y - GAP) / 2)
    const issue = graph.nodes.find((n) => n.type === 'issue')
    if (issue) pos[issue.id] = { x: 800, y: mid }
    graph.nodes.filter((n) => n.type === 'intervention').forEach((n, i) => { pos[n.id] = { x: 800, y: mid + 170 + i * GAP } })
    const right = graph.nodes.filter((n) => n.type === 'signal_group' && !placed.has(n.id))
    right.forEach((n, i) => { pos[n.id] = { x: 1200, y: i * GAP } })
    graph.nodes.filter((n) => n.type === 'segment').forEach((n, i) => { pos[n.id] = { x: 1200, y: right.length * GAP + 30 + i * GAP } })
    let loose = 0
    const ns: Node<GNodeData>[] = graph.nodes.map((n) => {
      const meta = n.type === 'hypothesis' ? `${pct(n.confidence)} confidence · ${title(n.status)}` : n.type === 'issue' ? `${title(n.severity)} · ${n.support} signals`
        : n.type === 'segment' ? `${pct(n.rate)} affected · ${n.lift?.toFixed(1)}x lift` : n.type === 'intervention' ? `${title(n.status)}${n.recommended ? ' · recommended' : ''}` : n.kind ? title(n.kind) : undefined
      const p = pos[n.id] ?? { x: 0, y: y + 40 + loose++ * GAP }  // evidence shared by several hypotheses keeps its first position
      return { id: n.id, type: 'g', position: p, data: { type: n.type, label: n.label ?? n.title, meta, selected: sel === n.id } }
    })
    const es: Edge[] = graph.edges.map((e, i) => {
      const st = EDGE[e.relation] ?? EDGE.reports
      return {
        id: `e${i}`, source: e.source, target: e.target, label: st.label, animated: false, markerEnd: { type: MarkerType.ArrowClosed, color: st.color },
        style: { stroke: st.color, strokeWidth: 1 + Math.min(1, Math.abs(e.weight ?? 0.3)) * 2.5, strokeDasharray: st.dash }, labelStyle: { fontSize: 10, fill: '#52514e' }, labelBgStyle: { fill: '#fff', fillOpacity: 0.9 },
      }
    })
    return { nodes: ns, edges: es }
  }, [graph, sel])
  const selected = graph.nodes.find((n) => n.id === sel)
  return (
    <div className="grid gap-4 lg:grid-cols-[1fr_300px]">
      <div className="h-[620px] overflow-hidden rounded-xl border border-line bg-slate-50" role="img" aria-label="Interactive evidence graph linking signals, events, hypotheses, the issue, segments and interventions">
        <ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} fitView fitViewOptions={{ padding: 0.15 }} minZoom={0.2} onNodeClick={(_, n) => setSel(n.id)} onPaneClick={() => setSel(null)} nodesConnectable={false}>
          <Background gap={20} color="#e3e8ef" />
          <Controls showInteractive={false} />
        </ReactFlow>
      </div>
      <div className="space-y-3">
        <div className="rounded-xl border border-line bg-white p-4">
          <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted">Legend</p>
          <ul className="space-y-1.5 text-xs">
            {Object.entries(EDGE).map(([k, v]) => <li key={k} className="flex items-center gap-2"><svg width="34" height="8"><line x1="0" y1="4" x2="34" y2="4" stroke={v.color} strokeWidth="2.5" strokeDasharray={v.dash} /></svg>{v.label}</li>)}
          </ul>
          <p className="mt-2 text-[11px] text-muted">Line thickness reflects evidence weight. Click a node for details; drag to rearrange.</p>
        </div>
        <div className="rounded-xl border border-line bg-white p-4">
          <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted">Selection</p>
          {!selected ? <p className="text-sm text-muted">Select a node to read its evidence.</p> : (
            <div className="space-y-2 text-sm">
              <Badge tone="blue" icon={<FileText size={11} />}>{STYLE[selected.type]?.name}</Badge>
              <p className="font-medium">{selected.title ?? selected.label}</p>
              {selected.confidence != null && <p className="text-xs text-ink-2">Confidence {pct(selected.confidence)} · {selected.quality} evidence quality</p>}
              {selected.causal_claim && <p className="rounded-md bg-amber-50 p-2 text-xs text-amber-900">{selected.causal_claim}</p>}
              {selected.signal_ids && <p className="text-xs text-muted">Sampled signal ids: {selected.signal_ids.join(', ')}</p>}
              {graph.edges.filter((e) => e.source === selected.id || e.target === selected.id).slice(0, 6).map((e, i) => <p key={i} className="text-xs text-ink-2">• {e.summary ?? e.relation}</p>)}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
