import { useState, type FormEvent } from 'react'
import { ShieldCheck } from 'lucide-react'
import { useAuth } from '@/lib/auth'
import { errorMessage } from '@/lib/api'
import { Button, Field, inputCls } from '@/components/ui'

const DEMO = [
  { role: 'Admin', email: 'admin@cxsentinel.ai' },
  { role: 'Analyst', email: 'analyst@cxsentinel.ai' },
  { role: 'Approver', email: 'approver@cxsentinel.ai' },
  { role: 'Viewer', email: 'viewer@cxsentinel.ai' },
]

export default function Login() {
  const { login } = useAuth()
  const [email, setEmail] = useState('approver@cxsentinel.ai')
  const [password, setPassword] = useState('')
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)

  async function submit(e: FormEvent) {
    e.preventDefault()
    setBusy(true); setErr('')
    try { await login(email, password) } catch (x) { setErr(errorMessage(x)) } finally { setBusy(false) }
  }

  return (
    <div className="grid min-h-full lg:grid-cols-[1.1fr_1fr]">
      <div className="hidden flex-col justify-between bg-ink p-12 text-white lg:flex">
        <div className="flex items-center gap-3"><img src="/favicon.svg" alt="" className="size-9" /><span className="text-lg font-semibold">CX Sentinel AI</span></div>
        <div>
          <h1 className="max-w-lg text-4xl font-semibold leading-tight">From unhappy customers to <span className="text-teal-300">verified recovery</span>.</h1>
          <p className="mt-4 max-w-lg text-slate-300">Eight coordinated agents detect emerging problems, investigate probable root causes, estimate impact, plan interventions, execute approved actions and prove whether the experience actually improved.</p>
          <ol className="mt-8 flex flex-wrap gap-2 text-xs font-medium text-slate-200">
            {['Signal', 'Issue', 'Segment', 'Root cause', 'Impact', 'Intervention', 'Execution', 'Verification'].map((s, i) => (
              <li key={s} className="flex items-center gap-2"><span className="rounded-full bg-white/10 px-2.5 py-1">{s}</span>{i < 7 && <span className="text-slate-500">→</span>}</li>
            ))}
          </ol>
        </div>
        <p className="text-xs text-slate-400">TCS AI Engineering Hackathon · Challenge 06 · All demo data is simulated.</p>
      </div>
      <div className="grid place-items-center p-6">
        <form onSubmit={submit} className="w-full max-w-sm space-y-4">
          <div className="mb-2"><ShieldCheck className="mb-3 text-brand" /><h2 className="text-2xl font-semibold">Sign in</h2><p className="mt-1 text-sm text-ink-2">Role-based access: viewers read, analysts investigate, approvers authorise actions.</p></div>
          <Field label="Email"><input className={inputCls} type="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} required /></Field>
          <Field label="Password"><input className={inputCls} type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required /></Field>
          {err && <p role="alert" className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{err}</p>}
          <Button type="submit" variant="primary" className="w-full" loading={busy}>Sign in</Button>
          <div className="rounded-lg border border-line bg-white p-3">
            <p className="mb-2 text-xs font-medium text-ink-2">Demo accounts (password is set by DEMO_PASSWORD in the server .env)</p>
            <div className="flex flex-wrap gap-1.5">{DEMO.map((d) => <button type="button" key={d.role} onClick={() => setEmail(d.email)} className="rounded-md bg-slate-100 px-2 py-1 text-xs font-medium text-ink-2 hover:bg-slate-200">{d.role}</button>)}</div>
          </div>
        </form>
      </div>
    </div>
  )
}
