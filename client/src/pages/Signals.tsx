import { useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Download, FileUp, Flag, ShieldAlert, Sparkles, UploadCloud } from 'lucide-react'
import { api, get, post } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import { date, num, title } from '@/lib/format'
import { Async, Badge, Banner, Button, Card, EmptyState, Field, inputCls, Meter, PageHeader, Spinner, Table, Tabs, Td, Th, Drawer, KV } from '@/components/ui'
import { BarsChart, ChartCard } from '@/components/charts'
import { toast } from '@/components/toast'

type Tab = 'explore' | 'upload' | 'sources'
const TYPE_TONE: Record<string, any> = { review: 'blue', ticket: 'teal', social: 'violet', survey: 'amber', transaction: 'neutral', telemetry: 'neutral', operational_metric: 'neutral' }

function Explore() {
  const [f, setF] = useState({ q: '', source_type: '', aspect: '', flagged: '', page: 1 })
  const [semantic, setSemantic] = useState(false)
  const [open, setOpen] = useState<number | null>(null)
  const list = useQuery({ queryKey: ['signals', f], queryFn: () => get<any>('/signals', { q: f.q || undefined, source_type: f.source_type || undefined, aspect: f.aspect || undefined, flagged: f.flagged === '' ? undefined : f.flagged === 'yes', page: f.page, size: 20 }), enabled: !semantic })
  const sem = useQuery({ queryKey: ['semantic', f.q], queryFn: () => get<any>('/signals/semantic', { q: f.q, k: 15 }), enabled: semantic && f.q.trim().length >= 3 })
  const detail = useQuery({ queryKey: ['signal', open], queryFn: () => get<any>(`/signals/${open}`), enabled: open != null })
  const summary = useQuery({ queryKey: ['signal-summary'], queryFn: () => get<any>('/signals/summary') })
  const items = semantic ? sem.data?.items : list.data?.items
  return (
    <div className="space-y-5">
      <Async q={summary}>
        {(s) => (
          <ChartCard title="Customer-voice volume" subtitle="Reviews, tickets, social posts and surveys per day" table={{ headers: ['Date', 'Reviews', 'Tickets', 'Social', 'Surveys'], rows: s.daily_voice.map((d: any) => [d.date, d.review ?? 0, d.ticket ?? 0, d.social ?? 0, d.survey ?? 0]) }}>
            <BarsChart data={s.daily_voice} xKey="date" stacked height={200} series={[{ key: 'review', label: 'Reviews' }, { key: 'ticket', label: 'Tickets' }, { key: 'social', label: 'Social' }, { key: 'survey', label: 'Surveys' }]} />
          </ChartCard>
        )}
      </Async>
      <Card title="Evidence" subtitle="Normalised signals from every connected source" actions={<label className="flex items-center gap-1.5 text-xs text-ink-2"><input type="checkbox" checked={semantic} onChange={(e) => setSemantic(e.target.checked)} /><Sparkles size={13} />Semantic search</label>} pad={false}>
        <div className="grid gap-3 border-b border-line-2 p-4 md:grid-cols-4">
          <Field label={semantic ? 'Describe what you are looking for' : 'Search text, id or product'}><input className={inputCls} value={f.q} onChange={(e) => setF({ ...f, q: e.target.value, page: 1 })} placeholder="e.g. courier never called" /></Field>
          <Field label="Source"><select className={inputCls} value={f.source_type} disabled={semantic} onChange={(e) => setF({ ...f, source_type: e.target.value, page: 1 })}><option value="">All sources</option>{Object.keys(TYPE_TONE).map((t) => <option key={t} value={t}>{title(t)}</option>)}</select></Field>
          <Field label="Aspect"><select className={inputCls} value={f.aspect} disabled={semantic} onChange={(e) => setF({ ...f, aspect: e.target.value, page: 1 })}><option value="">All aspects</option>{['delivery', 'payment', 'app', 'product_quality', 'refund', 'support', 'pricing', 'packaging'].map((t) => <option key={t} value={t}>{title(t)}</option>)}</select></Field>
          <Field label="Guardrail"><select className={inputCls} value={f.flagged} disabled={semantic} onChange={(e) => setF({ ...f, flagged: e.target.value, page: 1 })}><option value="">All</option><option value="yes">Prompt-injection flagged</option><option value="no">Clean</option></select></Field>
        </div>
        {(semantic ? sem.isLoading : list.isLoading) ? <Spinner /> : !items?.length ? <EmptyState title="No evidence matches" hint={semantic ? 'Type at least 3 characters.' : 'Try clearing a filter.'} /> : (
          <Table>
            <thead><tr><Th>When</Th><Th>Source</Th><Th>Evidence</Th><Th>Aspect</Th><Th>Sentiment</Th><Th>Reliability</Th><Th>{semantic ? 'Similarity' : 'Region'}</Th></tr></thead>
            <tbody>
              {items.map((s: any) => (
                <tr key={s.id} className="cursor-pointer hover:bg-slate-50" onClick={() => setOpen(s.id)}>
                  <Td className="whitespace-nowrap text-xs text-ink-2">{date(s.occurred_at, true)}</Td>
                  <Td><Badge tone={TYPE_TONE[s.source_type]}>{title(s.source_type)}</Badge></Td>
                  <Td className="max-w-lg"><div className="line-clamp-2">{s.text ?? `${title(s.metric_name)}: ${num(s.numeric_value, 2)}`}</div>{s.is_flagged && <Badge tone="red" icon={<ShieldAlert size={11} />} className="mt-1">Neutralised: {s.flag_reason}</Badge>}{s.revision > 1 && <Badge tone="amber" className="mt-1">rev {s.revision}</Badge>}{s.is_injected && <Badge tone="violet" className="mt-1">scenario</Badge>}</Td>
                  <Td>{s.primary_aspect ? title(s.primary_aspect) : '-'}</Td>
                  <Td className="tnum">{s.sentiment == null ? '-' : s.sentiment.toFixed(2)}</Td>
                  <Td className="w-28"><Meter value={s.reliability} tone="teal" /></Td>
                  <Td className="tnum text-xs text-ink-2">{semantic ? s.similarity.toFixed(2) : s.region ?? '-'}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
        {!semantic && list.data && (
          <div className="flex items-center justify-between border-t border-line-2 px-4 py-2.5 text-xs text-ink-2">
            <span>{num(list.data.total)} records</span>
            <div className="flex gap-2"><Button size="sm" disabled={f.page <= 1} onClick={() => setF({ ...f, page: f.page - 1 })}>Previous</Button><Button size="sm" disabled={f.page * 20 >= list.data.total} onClick={() => setF({ ...f, page: f.page + 1 })}>Next</Button></div>
          </div>
        )}
        {semantic && sem.data && <p className="border-t border-line-2 px-4 py-2 text-xs text-muted">Embedding backend: {sem.data.backend}</p>}
      </Card>
      <Drawer open={open != null} onClose={() => setOpen(null)} title="Evidence record">
        <Async q={detail}>
          {(d) => (
            <div className="space-y-4">
              <dl className="divide-y divide-line-2 text-sm"><KV k="Source ID" v={d.external_id} /><KV k="Source type" v={title(d.source_type)} /><KV k="Timestamp" v={date(d.occurred_at, true)} /><KV k="Customer (pseudonymous)" v={d.customer_id ? `#${d.customer_id}` : 'anonymous'} />
                <KV k="Product / service" v={d.product ?? '-'} /><KV k="Segment" v={d.segment ?? '-'} /><KV k="Region" v={d.region ?? '-'} /><KV k="Source reliability" v={d.reliability} /><KV k="Revision" v={d.revision} /></dl>
              {d.text && <div><p className="mb-1 text-xs font-medium text-muted">Text (sanitised, PII masked)</p><p className="rounded-lg bg-slate-50 p-3 text-sm">{d.text}</p></div>}
              <div><p className="mb-1 text-xs font-medium text-muted">Attributes</p><pre className="max-h-72 overflow-auto rounded-lg bg-slate-50 p-3 text-xs">{JSON.stringify(d.attributes, null, 2)}</pre></div>
            </div>
          )}
        </Async>
      </Drawer>
    </div>
  )
}

function Upload() {
  const { can } = useAuth()
  const qc = useQueryClient()
  const input = useRef<HTMLInputElement>(null)
  const [file, setFile] = useState<File | null>(null)
  const [dtype, setDtype] = useState('')
  const [report, setReport] = useState<any>(null)
  const datasets = useQuery({ queryKey: ['datasets'], queryFn: () => get<any[]>('/data/datasets') })
  const send = useMutation({
    mutationFn: async (dry: boolean) => {
      const fd = new FormData()
      fd.append('file', file!); fd.append('dry_run', String(dry)); if (dtype) fd.append('dataset_type', dtype)
      return (await api.post('/data/upload', fd)).data
    },
    onSuccess: (r, dry) => { setReport(r); if (!dry) { toast.success(`Ingested ${r.inserted} new and ${r.revised} revised records`); qc.invalidateQueries() } },
    onError: toast.error,
  })
  if (!can('analyst')) return <Banner tone="amber">Uploading data requires the analyst or approver role.</Banner>
  return (
    <div className="grid gap-5 xl:grid-cols-2">
      <Card title="1. Choose a CSV or XLSX file" subtitle="The dataset type is detected from the columns; you can override it.">
        <div role="button" tabIndex={0} onClick={() => input.current?.click()} onKeyDown={(e) => e.key === 'Enter' && input.current?.click()}
          onDragOver={(e) => e.preventDefault()} onDrop={(e) => { e.preventDefault(); setFile(e.dataTransfer.files[0] ?? null); setReport(null) }}
          className="flex cursor-pointer flex-col items-center gap-2 rounded-xl border-2 border-dashed border-line bg-slate-50 px-4 py-10 text-center hover:border-brand/50">
          <UploadCloud className="text-muted" />
          <p className="text-sm font-medium">{file ? file.name : 'Drop a file here or click to browse'}</p>
          <p className="text-xs text-muted">{file ? `${(file.size / 1024).toFixed(1)} KB` : 'Reviews, tickets, social, surveys, transactions, telemetry, metrics, events, releases, customers'}</p>
          <input ref={input} type="file" accept=".csv,.xlsx,.xlsm" hidden onChange={(e) => { setFile(e.target.files?.[0] ?? null); setReport(null) }} />
        </div>
        <div className="mt-4 grid gap-3 sm:grid-cols-2">
          <Field label="Dataset type"><select className={inputCls} value={dtype} onChange={(e) => setDtype(e.target.value)}><option value="">Auto-detect</option>{datasets.data?.map((d) => <option key={d.type} value={d.type}>{d.label}</option>)}</select></Field>
        </div>
        <div className="mt-4 flex gap-2">
          <Button icon={<FileUp size={15} />} disabled={!file} loading={send.isPending && send.variables === true} onClick={() => send.mutate(true)}>Validate &amp; preview</Button>
          <Button variant="primary" disabled={!file || !report || report.dry_run === false || report.accepted === 0} loading={send.isPending && send.variables === false} onClick={() => send.mutate(false)}>Ingest {report?.accepted ?? ''} valid rows</Button>
        </div>
        <p className="mt-3 text-xs text-muted">Uploads are idempotent: re-uploading the same file creates no duplicates; changed records become new revisions. Customer text is sanitised against prompt injection and PII is masked before storage.</p>
      </Card>
      <Card title="2. Validation report" subtitle="Rows that fail validation are rejected, never silently fixed.">
        {!report ? <EmptyState title="No file validated yet" hint="Validate a file to see errors and a normalised preview." /> : (
          <div className="space-y-4">
            <div className="flex flex-wrap items-center gap-2"><Badge tone="blue">{report.label}</Badge><Badge tone="green">{report.accepted} accepted</Badge><Badge tone={report.rejected ? 'red' : 'neutral'}>{report.rejected} rejected</Badge>
              {report.in_file_duplicates > 0 && <Badge tone="amber">{report.in_file_duplicates} duplicate ids</Badge>}{!report.dry_run && <><Badge tone="teal">{report.inserted} inserted</Badge><Badge tone="amber">{report.revised} revised</Badge><Badge tone="neutral">{report.unchanged} unchanged</Badge></>}
              {report.flagged_injection > 0 && <Badge tone="red" icon={<Flag size={11} />}>{report.flagged_injection} prompt-injection flagged</Badge>}</div>
            {report.errors?.length > 0 && <Table><thead><tr><Th>Row</Th><Th>Field</Th><Th>Problem</Th></tr></thead><tbody>{report.errors.map((e: any, i: number) => <tr key={i}><Td>{e.row}</Td><Td>{e.field}</Td><Td>{e.message}</Td></tr>)}</tbody></Table>}
            {report.preview && <div><p className="mb-1 text-xs font-medium text-muted">Normalised preview (first {report.preview.length})</p><pre className="max-h-64 overflow-auto rounded-lg bg-slate-50 p-3 text-[11px]">{JSON.stringify(report.preview.slice(0, 5), null, 2)}</pre></div>}
          </div>
        )}
      </Card>
    </div>
  )
}

function Sources() {
  const { can } = useAuth()
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['sources'], queryFn: () => get<any[]>('/data/sources') })
  const samples = useQuery({ queryKey: ['samples'], queryFn: () => get<any[]>('/data/samples') })
  const load = useMutation({ mutationFn: () => post('/data/load-samples'), onSuccess: () => { toast.success('Sample datasets loaded'); qc.invalidateQueries() }, onError: toast.error })
  const download = async (name: string) => {
    const r = await api.get(`/data/samples/${name}`, { responseType: 'blob' })
    const a = document.createElement('a'); a.href = URL.createObjectURL(r.data); a.download = name; a.click(); URL.revokeObjectURL(a.href)
  }
  return (
    <div className="space-y-5">
      <Card title="Connected data sources" subtitle="Reliability weights how much each source can sway a hypothesis" pad={false}
        actions={can('analyst') ? <Button size="sm" loading={load.isPending} onClick={() => load.mutate()}>Load sample datasets</Button> : undefined}>
        <Async q={q}>
          {(rows) => !rows.length ? <EmptyState title="No sources connected" hint="Load the sample datasets or upload your own files." /> : (
            <Table><thead><tr><Th>Source</Th><Th>Type</Th><Th>Records</Th><Th>Rejected</Th><Th>Reliability</Th><Th>Last ingested</Th></tr></thead>
              <tbody>{rows.map((s) => <tr key={s.id}><Td><div className="font-medium">{s.name}</div>{s.is_simulated && <Badge tone="teal">Simulated</Badge>}</Td><Td>{title(s.source_type)}</Td><Td className="tnum">{num(s.records)}</Td><Td className="tnum">{s.rejected}</Td><Td className="w-40"><Meter value={s.reliability} tone="teal" /></Td><Td className="text-xs text-ink-2">{date(s.last_ingested_at, true)}</Td></tr>)}</tbody></Table>
          )}
        </Async>
      </Card>
      <Card title="Simulated sample datasets" subtitle="Download and upload them through the Upload tab to exercise the full ingestion path" pad={false}>
        <Async q={samples}>{(rows) => (
          <Table><thead><tr><Th>File</Th><Th>Dataset type</Th><Th>Size</Th><Th /></tr></thead>
            <tbody>{rows.map((s) => <tr key={s.name}><Td className="font-medium">{s.name}</Td><Td>{title(s.dataset_type)}</Td><Td>{s.size_kb} KB</Td><Td className="text-right"><Button size="sm" variant="ghost" icon={<Download size={14} />} onClick={() => download(s.name)}>Download</Button></Td></tr>)}</tbody></Table>
        )}</Async>
      </Card>
    </div>
  )
}

export default function Signals() {
  const [tab, setTab] = useState<Tab>('explore')
  return (
    <>
      <PageHeader title="Customer Signal Explorer" description="Import, validate and normalise multi-source evidence, then search it with keyword or semantic queries. Every record carries a source ID, timestamp, segment, region and reliability." />
      <Tabs value={tab} onChange={setTab} tabs={[{ id: 'explore', label: 'Explore evidence' }, { id: 'upload', label: 'Upload & validate' }, { id: 'sources', label: 'Sources & samples' }]} />
      {tab === 'explore' ? <Explore /> : tab === 'upload' ? <Upload /> : <Sources />}
    </>
  )
}
