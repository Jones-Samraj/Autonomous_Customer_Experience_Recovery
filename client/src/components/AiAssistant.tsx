import { useEffect, useRef, useState, type KeyboardEvent } from 'react'
import { useLocation } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import {
  Bot,
  Sparkles,
  X,
  Send,
  RotateCcw,
  Loader2,
  ChevronDown,
} from 'lucide-react'
import { get } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import { cn } from './ui'

interface Message {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  timestamp: Date
}

const OPENROUTER_API_KEY = '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'
const MODEL_NAME = 'openai/gpt-4o-mini'

const PAGE_CONTEXTS: Record<string, string> = {
  '/': 'Executive Overview dashboard showing top-level customer health, active incident counts, revenue at risk, and service success rates.',
  '/signals': 'Signal Explorer displaying raw ingested customer signals (reviews, tweets, tickets, surveys, telemetry) with PII masking and prompt-injection filtering.',
  '/issues': 'Issue Intelligence showing detected emerging issue clusters generated via HDBSCAN clustering on text embeddings.',
  '/investigations': 'Root Cause Analysis featuring competing causal hypotheses, supporting vs contradicting evidence, and the interactive Evidence Graph.',
  '/impact': 'Customer Impact showing financial loss estimates (Revenue at Risk, Churn rate) and Fisher-exact tested customer demographic segments.',
  '/interventions': 'Intervention Center displaying ranked candidate recovery actions evaluated via Multi-Attribute Utility Theory (MAUT).',
  '/approvals': 'Approval Center where high-impact or consequential interventions require human authorization before execution.',
  '/monitoring': 'Recovery Monitoring verifying if post-execution cohorts actually improved using two-proportion binomial z-tests.',
  '/simulator': 'Jury Simulator where unexpected surprise evidence can be injected to watch hypotheses and intervention plans dynamically re-adapt.',
  '/evaluation': 'AI Evaluation Center measuring groundedness, precision, recall, and agent benchmark metrics against ground truth.',
  '/history': 'Execution History auditing every agent thought, LangGraph state transition, and tool call.',
}

const DEFAULT_PROMPTS = [
  { label: 'Explain this page', prompt: 'Can you explain what this current page does and what I should look at?' },
  { label: 'Jury walkthrough tips', prompt: 'What key points should I highlight to the judges during our demo presentation?' },
  { label: 'Explain root causes', prompt: 'How does the platform investigate and prove root causes without hallucinating?' },
  { label: 'How recovery works', prompt: 'How does verification work after an approved action is executed?' },
]

export default function AiAssistant() {
  const [isOpen, setIsOpen] = useState(false)
  const [isMinimized, setIsMinimized] = useState(false)
  const [input, setInput] = useState('')
  const [messages, setMessages] = useState<Message[]>([
    {
      id: 'welcome',
      role: 'assistant',
      content:
        "👋 **Hi! I'm your CX Sentinel AI Copilot.**\n\nI can explain active incidents, clarify root-cause evidence, guide you on what to present to the judges, or explain any formula on this page. What would you like to know?",
      timestamp: new Date(),
    },
  ])
  const [isLoading, setIsLoading] = useState(false)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const location = useLocation()
  const { user } = useAuth()

  // Fetch live context from the overview endpoint to inject into AI reasoning
  const overviewQ = useQuery({
    queryKey: ['overview'],
    queryFn: () => get<any>('/dashboard/overview'),
    staleTime: 60000,
  })

  // Auto-scroll to bottom on new message
  useEffect(() => {
    if (isOpen && !isMinimized) {
      messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
    }
  }, [messages, isOpen, isMinimized])

  // Focus input when opened
  useEffect(() => {
    if (isOpen && !isMinimized) {
      inputRef.current?.focus()
    }
  }, [isOpen, isMinimized])

  const handleSend = async (userText?: string) => {
    const text = (userText ?? input).trim()
    if (!text || isLoading) return

    const userMsg: Message = {
      id: String(Date.now()),
      role: 'user',
      content: text,
      timestamp: new Date(),
    }

    setMessages((prev) => [...prev, userMsg])
    if (!userText) setInput('')
    setIsLoading(true)

    // Build system prompt with live application data
    const activeRoute = location.pathname
    const pageDesc = PAGE_CONTEXTS[activeRoute] || 'CX Sentinel platform workspace'
    const kpiData = overviewQ.data?.kpis || {}

    const systemPrompt = `You are CX Sentinel Copilot, an expert AI assistant embedded inside "CX Sentinel AI" (an Autonomous Customer Experience Intelligence & Recovery Platform built for the TCS AI Hackathon).

CURRENT CONTEXT:
- Current Page: ${activeRoute} (${pageDesc})
- Current User: ${user?.full_name || 'Operator'} (Role: ${user?.role || 'analyst'})
- Platform Status: ${kpiData.total_issues ?? 'several'} detected issues, ${kpiData.critical_issues ?? 'multiple'} critical issues, Revenue at Risk: INR ${kpiData.revenue_at_risk?.toLocaleString?.() ?? 'active'}, Pending Approvals: ${kpiData.pending_approvals ?? 0}.

CORE PLATFORM KNOWLEDGE:
1. 8-Step Lifecycle: Signal -> Issue -> Segment -> Root Cause -> Impact -> Intervention -> Execution -> Verification.
2. Architecture: Multi-Agent LangGraph supervisor, HDBSCAN clustering on text embeddings (all-MiniLM-L6-v2 with TF-IDF fallback), IsolationForest anomaly cross-check, Fisher exact segmentation, Mantel-Haenszel risk difference, VADER sentiment.
3. Causal Evidence: Competing hypotheses with supporting AND contradicting evidence; interactive evidence graph.
4. Human Approval: Consequential actions (budget > ₹50,000 or config/partner reassignments) require Human Approver.
5. Verification: Executing an action never assumes recovery. Verification Agent monitors post-intervention cohort using two-proportion z-tests; failure automatically reopens the investigation.
6. Dynamic Jury Simulator: Users can inject surprise evidence (e.g. Mumbai monsoon traffic) to demonstrate dynamic belief revision in real time.

GUIDELINES:
- Give concise, direct, helpful answers formatted nicely with markdown bullet points and bold highlights.
- If asked about what to present to judges, give an actionable step-by-step walkthrough.
- Maintain a sharp, executive, technically confident tone.`

    // Prepare API history (last 8 messages)
    const apiMessages = [
      { role: 'system', content: systemPrompt },
      ...messages.slice(-8).map((m) => ({ role: m.role, content: m.content })),
      { role: 'user', content: text },
    ]

    try {
      const response = await fetch('https://openrouter.ai/api/v1/chat/completions', {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${OPENROUTER_API_KEY}`,
          'Content-Type': 'application/json',
          'HTTP-Referer': window.location.origin,
          'X-Title': 'CX Sentinel AI Copilot',
        },
        body: JSON.stringify({
          model: MODEL_NAME,
          messages: apiMessages,
          temperature: 0.3,
          max_tokens: 650,
        }),
      })

      if (!response.ok) {
        const errorText = await response.text()
        throw new Error(`OpenRouter error (${response.status}): ${errorText}`)
      }

      const data = await response.json()
      const reply = data.choices?.[0]?.message?.content || 'I processed that, but received an empty response. Please ask again.'

      const assistantMsg: Message = {
        id: String(Date.now() + 1),
        role: 'assistant',
        content: reply,
        timestamp: new Date(),
      }
      setMessages((prev) => [...prev, assistantMsg])
    } catch (err: any) {
      const errorMsg: Message = {
        id: String(Date.now() + 1),
        role: 'assistant',
        content: `⚠️ **Connection Note**: ${err.message || 'Failed to contact AI service.'}\n\n*Tip: CX Sentinel operates with full deterministic mathematical fallback even when offline.*`,
        timestamp: new Date(),
      }
      setMessages((prev) => [...prev, errorMsg])
    } finally {
      setIsLoading(false)
    }
  }

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  const handleClear = () => {
    setMessages([
      {
        id: 'welcome-reset',
        role: 'assistant',
        content: 'Conversation cleared. How can I help you navigate or present CX Sentinel AI?',
        timestamp: new Date(),
      },
    ])
  }

  // Format simple markdown into paragraphs and bold text
  const renderMessageContent = (text: string) => {
    const lines = text.split('\n')
    return (
      <div className="space-y-1.5 text-xs leading-relaxed">
        {lines.map((line, idx) => {
          if (!line.trim()) return <div key={idx} className="h-1" />

          // Simple bold formatting
          const parts = line.split(/(\*\*.*?\*\*)/g)
          const formattedLine = parts.map((part, pIdx) => {
            if (part.startsWith('**') && part.endsWith('**')) {
              return <strong key={pIdx} className="font-semibold">{part.slice(2, -2)}</strong>
            }
            if (part.startsWith('`') && part.endsWith('`')) {
              return (
                <code key={pIdx} className="rounded bg-slate-100 px-1 py-0.5 text-[11px] font-mono text-ink">
                  {part.slice(1, -1)}
                </code>
              )
            }
            return part
          })

          if (line.startsWith('* ') || line.startsWith('- ')) {
            return (
              <div key={idx} className="flex items-start gap-1.5 pl-1">
                <span className="text-brand">•</span>
                <span>{formattedLine}</span>
              </div>
            )
          }

          return <p key={idx}>{formattedLine}</p>
        })}
      </div>
    )
  }

  return (
    <>
      {/* FLOATING ACTION BUTTON */}
      {!isOpen && (
        <div className="fixed bottom-6 right-6 z-50 flex items-center gap-2">
          {/* Subtle invitation prompt */}
          <div className="hidden sm:flex items-center gap-1.5 rounded-full border border-line bg-white/95 px-3 py-1.5 text-xs font-medium text-ink shadow-md backdrop-blur">
            <Sparkles size={13} className="text-amber-500 animate-pulse" />
            <span>Ask AI Copilot</span>
          </div>

          <button
            onClick={() => setIsOpen(true)}
            aria-label="Open AI Assistant"
            className="group relative flex size-13 items-center justify-center rounded-full bg-gradient-to-tr from-brand-700 via-brand to-indigo-600 text-white shadow-lg transition-all duration-300 hover:scale-105 hover:shadow-brand/40 focus:outline-none focus:ring-4 focus:ring-brand/20 active:scale-95"
          >
            <span className="absolute -top-0.5 -right-0.5 flex size-3.5">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75" />
              <span className="relative inline-flex size-3.5 rounded-full bg-emerald-500 border-2 border-white" />
            </span>
            <Bot size={24} className="transition-transform group-hover:rotate-6" />
          </button>
        </div>
      )}

      {/* CHAT WINDOW POPUP */}
      {isOpen && (
        <div
          className={cn(
            'fixed bottom-6 right-6 z-50 flex w-[430px] max-w-[calc(100vw-2rem)] flex-col overflow-hidden rounded-2xl border border-line bg-white shadow-2xl transition-all duration-200',
            isMinimized ? 'h-14' : 'h-[600px] max-h-[calc(100vh-5rem)]'
          )}
        >
          {/* Header */}
          <header className="flex h-14 shrink-0 items-center justify-between border-b border-line bg-slate-900 px-4 text-white">
            <div className="flex items-center gap-2.5">
              <div className="relative flex size-8 items-center justify-center rounded-lg bg-gradient-to-tr from-brand to-indigo-500">
                <Bot size={18} className="text-white" />
                <span className="absolute -bottom-0.5 -right-0.5 size-2 rounded-full bg-emerald-400 ring-2 ring-slate-900" />
              </div>
              <div className="leading-tight">
                <div className="flex items-center gap-1.5 text-sm font-semibold">
                  <span>CX Sentinel Copilot</span>
                  <span className="rounded bg-brand-500/20 px-1.5 py-0.2 text-[10px] font-medium text-brand-300 border border-brand-400/30">
                    GPT-4o-mini
                  </span>
                </div>
                <div className="text-[11px] text-slate-400">Autonomous CX Intelligence Assistant</div>
              </div>
            </div>

            <div className="flex items-center gap-1">
              <button
                onClick={handleClear}
                title="Clear conversation"
                className="rounded-md p-1.5 text-slate-400 hover:bg-slate-800 hover:text-white transition-colors"
              >
                <RotateCcw size={14} />
              </button>
              <button
                onClick={() => setIsMinimized(!isMinimized)}
                title={isMinimized ? 'Expand' : 'Minimize'}
                className="rounded-md p-1.5 text-slate-400 hover:bg-slate-800 hover:text-white transition-colors"
              >
                <ChevronDown size={16} className={cn('transition-transform', isMinimized && 'rotate-180')} />
              </button>
              <button
                onClick={() => setIsOpen(false)}
                title="Close"
                className="rounded-md p-1.5 text-slate-400 hover:bg-slate-800 hover:text-white transition-colors"
              >
                <X size={16} />
              </button>
            </div>
          </header>

          {/* Body when not minimized */}
          {!isMinimized && (
            <>
              {/* Context Banner */}
              <div className="flex items-center justify-between border-b border-line-2 bg-slate-50 px-3.5 py-1.5 text-[11px] text-muted">
                <div className="flex items-center gap-1 truncate">
                  <span className="size-1.5 rounded-full bg-brand" />
                  <span className="truncate">Watching: <strong>{location.pathname}</strong></span>
                </div>
                <span className="shrink-0 text-[10px] text-emerald-600 font-medium">● OpenRouter Connected</span>
              </div>

              {/* Messages Area */}
              <div className="flex-1 overflow-y-auto p-4 space-y-3.5 bg-slate-50/50">
                {messages.map((msg) => (
                  <div
                    key={msg.id}
                    className={cn('flex gap-2.5', msg.role === 'user' ? 'justify-end' : 'justify-start')}
                  >
                    {msg.role === 'assistant' && (
                      <div className="mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-full bg-brand text-white shadow-xs">
                        <Bot size={13} />
                      </div>
                    )}
                    <div
                      className={cn(
                        'max-w-[85%] rounded-2xl px-3.5 py-2.5 shadow-xs',
                        msg.role === 'user'
                          ? 'bg-brand text-white rounded-br-xs'
                          : 'bg-white border border-line text-ink rounded-bl-xs'
                      )}
                    >
                      {renderMessageContent(msg.content)}
                      <div
                        className={cn(
                          'mt-1 text-[9px] text-right',
                          msg.role === 'user' ? 'text-brand-100' : 'text-muted'
                        )}
                      >
                        {msg.timestamp.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                      </div>
                    </div>
                  </div>
                ))}

                {isLoading && (
                  <div className="flex items-center gap-2 text-xs text-muted pl-1">
                    <Loader2 size={13} className="animate-spin text-brand" />
                    <span>CX Copilot is analyzing evidence...</span>
                  </div>
                )}
                <div ref={messagesEndRef} />
              </div>

              {/* Quick Prompt Pills */}
              <div className="flex gap-1.5 overflow-x-auto border-t border-line-2 bg-white px-3 py-2 text-[11px] scrollbar-none">
                {DEFAULT_PROMPTS.map((p, i) => (
                  <button
                    key={i}
                    disabled={isLoading}
                    onClick={() => handleSend(p.prompt)}
                    className="flex shrink-0 items-center gap-1 rounded-full border border-line bg-slate-50 px-2.5 py-1 text-ink-2 hover:border-brand/40 hover:bg-brand-50 hover:text-brand transition-colors disabled:opacity-50"
                  >
                    <Sparkles size={10} className="text-amber-500" />
                    <span>{p.label}</span>
                  </button>
                ))}
              </div>

              {/* Input Area */}
              <div className="border-t border-line bg-white p-3">
                <div className="flex items-end gap-2 rounded-xl border border-line bg-slate-50/70 p-1.5 focus-within:border-brand focus-within:bg-white focus-within:ring-2 focus-within:ring-brand/20">
                  <textarea
                    ref={inputRef}
                    value={input}
                    onChange={(e) => setInput(e.target.value)}
                    onKeyDown={handleKeyDown}
                    rows={2}
                    placeholder="Ask about active issues, formulas, jury tips..."
                    className="w-full resize-none bg-transparent px-2 py-1 text-xs text-ink placeholder:text-muted focus:outline-none"
                  />
                  <button
                    onClick={() => handleSend()}
                    disabled={!input.trim() || isLoading}
                    aria-label="Send message"
                    className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-brand text-white transition-colors hover:bg-brand-700 disabled:cursor-not-allowed disabled:opacity-40"
                  >
                    {isLoading ? <Loader2 size={14} className="animate-spin" /> : <Send size={14} />}
                  </button>
                </div>
                <div className="mt-1 flex items-center justify-between px-1 text-[10px] text-muted">
                  <span>Press <strong>Enter</strong> to send, <strong>Shift+Enter</strong> for new line</span>
                  <span>Safety: PII masked</span>
                </div>
              </div>
            </>
          )}
        </div>
      )}
    </>
  )
}
