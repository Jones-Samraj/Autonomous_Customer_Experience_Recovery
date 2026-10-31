import { useEffect, useState } from 'react'
import { CheckCircle2, Info, XCircle } from 'lucide-react'
import { errorMessage } from '@/lib/api'
import { cn } from './ui'

interface Toast { id: number; tone: 'success' | 'error' | 'info'; text: string }
const listeners = new Set<(t: Toast) => void>()
let seq = 0

export const toast = {
  success: (text: string) => emit('success', text),
  info: (text: string) => emit('info', text),
  error: (e: unknown) => emit('error', typeof e === 'string' ? e : errorMessage(e)),
}
function emit(tone: Toast['tone'], text: string) {
  const t = { id: ++seq, tone, text }
  listeners.forEach((l) => l(t))
}

export function Toaster() {
  const [items, setItems] = useState<Toast[]>([])
  useEffect(() => {
    const l = (t: Toast) => {
      setItems((x) => [...x, t])
      setTimeout(() => setItems((x) => x.filter((i) => i.id !== t.id)), t.tone === 'error' ? 8000 : 4500)
    }
    listeners.add(l)
    return () => { listeners.delete(l) }
  }, [])
  return (
    <div aria-live="polite" className="pointer-events-none fixed bottom-5 right-5 z-[60] flex w-96 max-w-[calc(100vw-2rem)] flex-col gap-2">
      {items.map((t) => (
        <div key={t.id} role={t.tone === 'error' ? 'alert' : 'status'} className={cn('pointer-events-auto flex items-start gap-2 rounded-xl border bg-white px-4 py-3 text-sm shadow-lg', t.tone === 'error' ? 'border-red-200' : 'border-line')}>
          {t.tone === 'success' ? <CheckCircle2 size={17} className="mt-0.5 shrink-0 text-good" /> : t.tone === 'error' ? <XCircle size={17} className="mt-0.5 shrink-0 text-critical" /> : <Info size={17} className="mt-0.5 shrink-0 text-brand" />}
          <span className="text-ink">{t.text}</span>
        </div>
      ))}
    </div>
  )
}
