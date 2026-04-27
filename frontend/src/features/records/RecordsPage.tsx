import { useState, useEffect, useCallback } from 'react'
import { recordsApi } from '@/api/records'
import type { OperationalRecord } from '@/api/records'
import { useToast } from '@/hooks/useToast'
import { Badge } from '@/components/common/Badge'
import { PageLoader } from '@/components/common/Spinner'

const TABS: { label: string; value: string }[] = [
  { label: '全部',       value: '' },
  { label: '处理中',     value: 'PENDING' },
  { label: '已处理',     value: 'PROCESSED' },
  { label: '待老板决策', value: 'PENDING_BOSS_DECISION' },
  { label: '人工审核',   value: 'MANUAL_REVIEW' },
]

export default function RecordsPage() {
  const [records, setRecords]   = useState<OperationalRecord[]>([])
  const [loading, setLoading]   = useState(true)
  const [text, setText]         = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [activeTab, setActiveTab]   = useState('')
  const { success, error } = useToast()

  const load = useCallback(async (status: string) => {
    setLoading(true)
    try { setRecords(await recordsApi.list(status || undefined)) }
    catch (e) { error((e as Error).message) }
    finally { setLoading(false) }
  }, [error])

  useEffect(() => { load(activeTab) }, [load, activeTab])

  const switchTab = (v: string) => { setActiveTab(v) }

  const submit = async () => {
    if (!text.trim()) { error('请输入流水内容'); return }
    setSubmitting(true)
    try {
      await recordsApi.create(text.trim())
      success('流水记录已提交'); setText(''); load(activeTab)
    } catch (e) { error((e as Error).message) }
    finally { setSubmitting(false) }
  }

  const statusBadge = (s: string) => {
    const m: Record<string, [string, 'green' | 'yellow' | 'gray' | 'red']> = {
      PROCESSED:             ['已处理',     'green'],
      PENDING:               ['处理中',     'yellow'],
      PENDING_BOSS_DECISION: ['待老板决策', 'red'],
      MANUAL_REVIEW:         ['人工审核',   'gray'],
    }
    const [l, v] = m[s] ?? [s, 'gray' as const]
    return <Badge variant={v}>{l}</Badge>
  }

  return (
    <div className="p-6 max-w-4xl">
      <h1 className="text-xl font-bold text-slate-800 mb-5">流水记录</h1>
      <div className="bg-white border border-slate-200 rounded-xl p-4 mb-5">
        <textarea value={text} onChange={e => setText(e.target.value)} rows={3}
          placeholder="输入业务描述，如：收到客户货款 50000 元"
          className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm resize-none focus:outline-none focus:ring-2 focus:ring-primary-500 mb-3" />
        <button onClick={submit} disabled={submitting}
          className="px-4 py-2 bg-primary-600 hover:bg-primary-700 disabled:bg-slate-300 text-white text-sm rounded-lg font-medium">
          {submitting ? '提交中…' : '提交'}
        </button>
      </div>

      {/* Status filter tabs */}
      <div className="flex gap-1 mb-3">
        {TABS.map(t => (
          <button
            key={t.value}
            onClick={() => switchTab(t.value)}
            className={`px-3 py-1.5 text-xs rounded-lg font-medium transition-colors ${
              activeTab === t.value
                ? 'bg-primary-600 text-white'
                : 'bg-white border border-slate-200 text-slate-600 hover:border-primary-400'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
        {loading ? (
          <div className="py-10 text-center text-slate-400 text-sm">加载中…</div>
        ) : (
          <table className="w-full text-sm"><thead className="bg-slate-50"><tr className="text-xs text-slate-500">
            <th className="px-4 py-3 text-left">内容</th><th className="px-4 py-3 text-center">状态</th><th className="px-4 py-3 text-left">时间</th>
          </tr></thead><tbody>
            {records.length === 0 && <tr><td colSpan={3} className="px-4 py-10 text-center text-slate-400">暂无记录</td></tr>}
            {records.map(r => (
              <tr key={r.record_id} className="border-t border-slate-100">
                <td className="px-4 py-3 truncate max-w-md">{r.raw_text}</td>
                <td className="px-4 py-3 text-center">{statusBadge(r.status)}</td>
                <td className="px-4 py-3 text-xs text-slate-400">{r.created_at?.slice(0, 16) ?? '—'}</td>
              </tr>
            ))}
          </tbody></table>
        )}
      </div>
    </div>
  )
}
