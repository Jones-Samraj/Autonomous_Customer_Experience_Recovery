import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { get } from '@/lib/api'
import type { AgentRun } from '@/lib/types'
import { Async, Button, Card, EmptyState, Field, inputCls, PageHeader } from '@/components/ui'
import { AgentRunsTable } from '@/components/AgentTimeline'

const AGENTS = ['Signal Intelligence Agent', 'Emerging Issue Detection Agent', 'Customer Segmentation Agent', 'Root Cause Investigation Agent', 'Evidence Validator', 'Business Impact Assessment Agent',
  'Intervention Planning Agent', 'Recovery Execution Agent', 'Verification & Learning Agent', 'Orchestrator (Supervisor)']

export default function HistoryPage() {
  const [agent, setAgent] = useState('')
  const [page, setPage] = useState(1)
  const q = useQuery({ queryKey: ['history', agent, page], queryFn: () => get<{ total: number; items: AgentRun[] }>('/history', { agent: agent || undefined, page, size: 40 }) })
  return (
    <>
      <PageHeader title="Decision and Execution History" description="Every agent step with its task, input evidence, concise reasoning summary, output, status and timestamp. Includes the orchestrator's routing decisions and execution retries." />
      <Card pad={false} actions={<Field label="Agent"><select className={`${inputCls} w-64`} value={agent} onChange={(e) => { setAgent(e.target.value); setPage(1) }}><option value="">All agents</option>{AGENTS.map((a) => <option key={a}>{a}</option>)}</select></Field>}
        title="Agent execution log">
        <Async q={q}>{(d) => !d.items.length ? <EmptyState title="No agent activity yet" hint="Run the full analysis from the Executive Overview." /> : (
          <>
            <AgentRunsTable runs={d.items} showIssue />
            <div className="flex items-center justify-between border-t border-line-2 px-4 py-2.5 text-xs text-ink-2"><span>{d.total} entries</span>
              <div className="flex gap-2"><Button size="sm" disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</Button><Button size="sm" disabled={page * 40 >= d.total} onClick={() => setPage(page + 1)}>Next</Button></div></div>
          </>)}</Async>
      </Card>
    </>
  )
}
