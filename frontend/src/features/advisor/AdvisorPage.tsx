import { useState, useRef, useEffect } from 'react'
import { api } from '@/api/client'

interface Source {
  strategy_id: string
  title: string
  source_doc: string
  similarity: number
  optimal_timing: string
}

interface Message {
  role: 'user' | 'assistant'
  content: string
  sources?: Source[]
}

interface AskResponse {
  answer: string
  sources: Source[]
}

export default function AdvisorPage() {
  const [messages, setMessages] = useState<Message[]>([])
  const [input,    setInput]    = useState('')
  const [loading,  setLoading]  = useState(false)
  const [expandedSources, setExpandedSources] = useState<Set<number>>(new Set())
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, loading])

  const send = async () => {
    const q = input.trim()
    if (!q || loading) return
    setInput('')

    const userMsg: Message = { role: 'user', content: q }
    const history = messages.map(m => ({ role: m.role, content: m.content }))
    setMessages(prev => [...prev, userMsg])
    setLoading(true)

    try {
      const res = await api.post<AskResponse>('/api/rag/ask', { question: q, history, top_k: 5 })
      setMessages(prev => [...prev, { role: 'assistant', content: res.answer, sources: res.sources }])
    } catch (e) {
      setMessages(prev => [...prev, { role: 'assistant', content: `请求失败：${(e as Error).message}` }])
    } finally {
      setLoading(false)
    }
  }

  const toggleSources = (idx: number) => {
    setExpandedSources(prev => {
      const next = new Set(prev)
      next.has(idx) ? next.delete(idx) : next.add(idx)
      return next
    })
  }

  return (
    <div className="flex flex-col h-[calc(100vh-4rem)] max-w-3xl mx-auto p-4">
      <h1 className="text-xl font-bold text-slate-800 mb-4 flex-shrink-0">AI 财税顾问</h1>

      {/* Chat area */}
      <div className="flex-1 overflow-y-auto space-y-4 mb-4 pr-1">
        {messages.length === 0 && (
          <div className="text-center text-slate-400 text-sm mt-16">
            <p className="text-2xl mb-2">💬</p>
            <p>您好！我是您的 AI 财税顾问。</p>
            <p className="mt-1">可以问我关于税务筹划、财务政策等问题。</p>
          </div>
        )}

        {messages.map((msg, i) => (
          <div key={i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            {msg.role === 'user' ? (
              <div className="max-w-[75%] bg-primary-600 text-white rounded-2xl rounded-tr-sm px-4 py-3 text-sm">
                {msg.content}
              </div>
            ) : (
              <div className="max-w-[85%]">
                <div className="bg-white border border-slate-200 rounded-2xl rounded-tl-sm px-4 py-3 text-sm text-slate-800 whitespace-pre-wrap">
                  {msg.content}
                </div>
                {msg.sources && msg.sources.length > 0 && (
                  <div className="mt-1 ml-1">
                    <button
                      onClick={() => toggleSources(i)}
                      className="text-xs text-slate-400 hover:text-slate-600 transition-colors"
                    >
                      {expandedSources.has(i) ? '▲ 收起' : '▼ 参考来源'} ({msg.sources.length})
                    </button>
                    {expandedSources.has(i) && (
                      <div className="mt-2 space-y-1">
                        {msg.sources.map((s, si) => (
                          <div key={si} className="bg-slate-50 border border-slate-200 rounded-lg px-3 py-2 text-xs">
                            <span className="font-medium text-slate-700">{s.title}</span>
                            <span className="text-slate-400 ml-2">相似度 {(s.similarity * 100).toFixed(0)}%</span>
                            {s.source_doc && <span className="text-slate-400 ml-2">· {s.source_doc}</span>}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </div>
            )}
          </div>
        ))}

        {loading && (
          <div className="flex justify-start">
            <div className="bg-white border border-slate-200 rounded-2xl rounded-tl-sm px-4 py-3">
              <span className="flex gap-1">
                <span className="w-2 h-2 bg-slate-300 rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
                <span className="w-2 h-2 bg-slate-300 rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
                <span className="w-2 h-2 bg-slate-300 rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
              </span>
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div className="flex-shrink-0 flex gap-2">
        <input
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send() } }}
          placeholder="输入问题，如：研发费用加计扣除如何操作？"
          disabled={loading}
          className="flex-1 border border-slate-200 rounded-xl px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500 disabled:bg-slate-50"
        />
        <button
          onClick={send}
          disabled={loading || !input.trim()}
          className="px-4 py-2.5 bg-primary-600 hover:bg-primary-700 disabled:bg-slate-300 text-white text-sm rounded-xl font-medium"
        >
          发送
        </button>
      </div>
    </div>
  )
}
