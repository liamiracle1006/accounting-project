import { useState, useEffect } from 'react'
import { api } from '@/api/client'
import { useToast } from '@/hooks/useToast'

interface Stats {
  total_slices: number
  collection_name: string
  chroma_path: string
}

interface SlicesResponse {
  count: number
  ids: string[]
}

interface SearchHit {
  strategy_id: string
  title: string
  similarity: number
  confidence: number
  optimal_timing: string
  source_doc: string
  core_content: string
  action_suggestions: string[]
  risk_notes: string
}

interface SearchResponse {
  query: string
  count: number
  hits: SearchHit[]
}

export default function KnowledgePage() {
  const [stats,   setStats]   = useState<Stats | null>(null)
  const [slices,  setSlices]  = useState<SlicesResponse | null>(null)
  const [idFilter, setIdFilter] = useState('')
  const [reloading, setReloading] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const [searchResult, setSearchResult] = useState<SearchResponse | null>(null)
  const [searching, setSearching] = useState(false)
  const [unavailable, setUnavailable] = useState(false)
  const { success, error } = useToast()

  useEffect(() => {
    Promise.all([
      api.get<Stats>('/api/rag/stats'),
      api.get<SlicesResponse>('/api/rag/slices'),
    ]).then(([s, sl]) => { setStats(s); setSlices(sl) })
      .catch(e => {
        const msg = (e as Error).message
        if (msg.includes('503') || msg.toLowerCase().includes('chromadb')) {
          setUnavailable(true)
        } else {
          error(msg)
        }
      })
  }, [])  // eslint-disable-line

  const reload = async () => {
    setReloading(true)
    try {
      const res = await api.post<any>('/api/rag/reload', {})
      success(`知识库重载完成：${JSON.stringify(res)}`)
      const [s, sl] = await Promise.all([
        api.get<Stats>('/api/rag/stats'),
        api.get<SlicesResponse>('/api/rag/slices'),
      ])
      setStats(s); setSlices(sl)
    } catch (e) { error((e as Error).message) }
    finally { setReloading(false) }
  }

  const search = async () => {
    if (!searchQuery.trim()) return
    setSearching(true)
    try {
      const res = await api.post<SearchResponse>('/api/rag/search', { query: searchQuery.trim(), top_k: 5 })
      setSearchResult(res)
    } catch (e) { error((e as Error).message) }
    finally { setSearching(false) }
  }

  const filteredIds = slices
    ? (idFilter ? slices.ids.filter(id => id.toLowerCase().includes(idFilter.toLowerCase())) : slices.ids)
    : []

  if (unavailable) {
    return (
      <div className="p-6 max-w-3xl">
        <h1 className="text-xl font-bold text-slate-800 mb-5">[Dev] 知识库管理</h1>
        <div className="bg-amber-50 border border-amber-200 rounded-xl p-5 text-sm text-amber-700">
          <p className="font-semibold mb-1">RAG 功能不可用</p>
          <p>chromadb 未安装。请安装 C++ Build Tools 后执行：<code className="font-mono bg-amber-100 px-1 rounded">pip install chromadb</code></p>
        </div>
      </div>
    )
  }

  return (
    <div className="p-6 max-w-4xl">
      <h1 className="text-xl font-bold text-slate-800 mb-5">[Dev] 知识库管理</h1>

      {/* Stats */}
      <div className="grid grid-cols-3 gap-4 mb-6">
        <div className="bg-white border border-slate-200 rounded-xl p-4">
          <p className="text-xs text-slate-400 mb-1">切片总数</p>
          <p className="text-2xl font-bold text-primary-600">{stats?.total_slices ?? '—'}</p>
        </div>
        <div className="bg-white border border-slate-200 rounded-xl p-4">
          <p className="text-xs text-slate-400 mb-1">集合名称</p>
          <p className="text-sm font-mono text-slate-700 truncate">{stats?.collection_name ?? '—'}</p>
        </div>
        <div className="bg-white border border-slate-200 rounded-xl p-4 flex items-center justify-center">
          <button
            onClick={reload}
            disabled={reloading}
            className="px-4 py-2 bg-primary-600 hover:bg-primary-700 disabled:bg-slate-300 text-white text-sm rounded-lg font-medium"
          >
            {reloading ? '重载中…' : '重载知识库'}
          </button>
        </div>
      </div>

      {/* Slice list */}
      <div className="mb-6">
        <div className="flex items-center gap-2 mb-3">
          <h2 className="text-sm font-semibold text-slate-700">切片列表</h2>
          <span className="text-xs text-slate-400">({filteredIds.length} / {slices?.count ?? 0})</span>
        </div>
        <input
          value={idFilter}
          onChange={e => setIdFilter(e.target.value)}
          placeholder="过滤 ID…"
          className="w-full mb-2 border border-slate-200 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500"
        />
        <div className="bg-white border border-slate-200 rounded-xl overflow-hidden max-h-48 overflow-y-auto">
          {filteredIds.length === 0 ? (
            <div className="px-4 py-6 text-center text-slate-400 text-sm">暂无切片</div>
          ) : (
            <ul className="divide-y divide-slate-100">
              {filteredIds.map(id => (
                <li key={id} className="px-4 py-2 text-xs font-mono text-slate-600 hover:bg-slate-50">{id}</li>
              ))}
            </ul>
          )}
        </div>
      </div>

      {/* Semantic search test */}
      <div>
        <h2 className="text-sm font-semibold text-slate-700 mb-3">语义检索测试</h2>
        <div className="flex gap-2 mb-4">
          <input
            value={searchQuery}
            onChange={e => setSearchQuery(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') search() }}
            placeholder="输入检索关键词，如：研发费加计扣除"
            className="flex-1 border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500"
          />
          <button
            onClick={search}
            disabled={searching || !searchQuery.trim()}
            className="px-4 py-2 bg-primary-600 hover:bg-primary-700 disabled:bg-slate-300 text-white text-sm rounded-lg font-medium"
          >
            {searching ? '检索中…' : '检索'}
          </button>
        </div>

        {searchResult && (
          <div>
            <p className="text-xs text-slate-400 mb-2">找到 {searchResult.count} 个结果</p>
            <div className="space-y-3">
              {searchResult.hits.map((h, i) => (
                <div key={i} className="bg-white border border-slate-200 rounded-xl p-4">
                  <div className="flex items-start justify-between mb-2">
                    <span className="font-medium text-sm text-slate-800">{h.title}</span>
                    <span className="text-xs text-slate-400 ml-2 flex-shrink-0">
                      相似度 {(h.similarity * 100).toFixed(0)}%
                    </span>
                  </div>
                  <p className="text-xs text-slate-500 mb-2 line-clamp-3">{h.core_content}</p>
                  {h.action_suggestions.length > 0 && (
                    <div className="mt-2">
                      <p className="text-xs text-slate-400 mb-1">建议操作：</p>
                      <ul className="list-disc list-inside text-xs text-slate-600 space-y-0.5">
                        {h.action_suggestions.map((s, si) => <li key={si}>{s}</li>)}
                      </ul>
                    </div>
                  )}
                  {h.source_doc && (
                    <p className="text-xs text-slate-400 mt-2">来源：{h.source_doc}</p>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
