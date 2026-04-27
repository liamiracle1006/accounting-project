import { useState, useCallback } from 'react'
import { api } from '@/api/client'
import { useToast } from '@/hooks/useToast'

interface AuditLog {
  log_id: number
  table_name: string
  record_id: string | number
  action: string
  username: string
  description: string
  ip_address: string | null
  created_at: string
}

interface AuditResponse {
  total: number
  items: AuditLog[]
}

const ACTION_OPTIONS = ['', 'CREATE', 'UPDATE', 'STATUS_CHANGE', 'DELETE']
const PAGE_SIZE = 50

const ACTION_COLOR: Record<string, string> = {
  CREATE:        'text-green-600 bg-green-50',
  UPDATE:        'text-blue-600 bg-blue-50',
  STATUS_CHANGE: 'text-amber-600 bg-amber-50',
  DELETE:        'text-red-600 bg-red-50',
}

export default function AuditLogPage() {
  const [tableName, setTableName] = useState('')
  const [action,    setAction]    = useState('')
  const [page,      setPage]      = useState(0)
  const [data,      setData]      = useState<AuditResponse | null>(null)
  const [loading,   setLoading]   = useState(false)
  const { error } = useToast()

  const search = useCallback(async (pageIdx = 0) => {
    setLoading(true)
    try {
      const params = new URLSearchParams({ limit: String(PAGE_SIZE), offset: String(pageIdx * PAGE_SIZE) })
      if (tableName.trim()) params.set('table_name', tableName.trim())
      if (action) params.set('action', action)
      const res = await api.get<AuditResponse>(`/api/audit-logs?${params}`)
      setData(res)
      setPage(pageIdx)
    } catch (e) { error((e as Error).message) }
    finally { setLoading(false) }
  }, [tableName, action, error])

  const totalPages = data ? Math.ceil(data.total / PAGE_SIZE) : 0

  return (
    <div className="p-6 max-w-6xl">
      <h1 className="text-xl font-bold text-slate-800 mb-5">操作日志</h1>

      {/* Filters */}
      <div className="bg-white border border-slate-200 rounded-xl p-4 mb-4 flex items-end gap-3">
        <div className="flex-1">
          <label className="text-xs text-slate-500 mb-1 block">数据表</label>
          <input
            value={tableName}
            onChange={e => setTableName(e.target.value)}
            placeholder="如：vouchers, subjects…"
            className="w-full border border-slate-200 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500"
          />
        </div>
        <div>
          <label className="text-xs text-slate-500 mb-1 block">操作类型</label>
          <select
            value={action}
            onChange={e => setAction(e.target.value)}
            className="border border-slate-200 rounded-lg px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500"
          >
            {ACTION_OPTIONS.map(o => <option key={o} value={o}>{o || '全部'}</option>)}
          </select>
        </div>
        <button
          onClick={() => search(0)}
          disabled={loading}
          className="px-4 py-1.5 bg-primary-600 hover:bg-primary-700 disabled:bg-slate-300 text-white text-sm rounded-lg font-medium"
        >
          {loading ? '查询中…' : '查询'}
        </button>
      </div>

      {/* Results */}
      {data && (
        <>
          <p className="text-xs text-slate-400 mb-2">共 {data.total} 条记录，当前第 {page + 1} / {Math.max(1, totalPages)} 页</p>
          <div className="bg-white border border-slate-200 rounded-xl overflow-hidden mb-3">
            <table className="w-full text-sm">
              <thead className="bg-slate-50">
                <tr className="text-xs text-slate-500">
                  <th className="px-4 py-3 text-left">日志ID</th>
                  <th className="px-4 py-3 text-left">数据表</th>
                  <th className="px-4 py-3 text-left">记录ID</th>
                  <th className="px-4 py-3 text-left">操作</th>
                  <th className="px-4 py-3 text-left">操作人</th>
                  <th className="px-4 py-3 text-left">描述</th>
                  <th className="px-4 py-3 text-left">IP</th>
                  <th className="px-4 py-3 text-left">时间</th>
                </tr>
              </thead>
              <tbody>
                {data.items.length === 0 && (
                  <tr><td colSpan={8} className="px-4 py-10 text-center text-slate-400">暂无日志</td></tr>
                )}
                {data.items.map(log => (
                  <tr key={log.log_id} className="border-t border-slate-100 hover:bg-slate-50">
                    <td className="px-4 py-2 text-xs text-slate-400">{log.log_id}</td>
                    <td className="px-4 py-2 font-mono text-xs">{log.table_name}</td>
                    <td className="px-4 py-2 text-xs">{log.record_id}</td>
                    <td className="px-4 py-2">
                      <span className={`text-xs px-2 py-0.5 rounded font-medium ${ACTION_COLOR[log.action] ?? 'text-slate-600 bg-slate-100'}`}>
                        {log.action}
                      </span>
                    </td>
                    <td className="px-4 py-2 text-xs">{log.username}</td>
                    <td className="px-4 py-2 text-xs text-slate-600 max-w-xs truncate">{log.description}</td>
                    <td className="px-4 py-2 text-xs text-slate-400">{log.ip_address ?? '—'}</td>
                    <td className="px-4 py-2 text-xs text-slate-400">{log.created_at.slice(0, 16)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Pagination */}
          {totalPages > 1 && (
            <div className="flex items-center gap-2">
              <button
                onClick={() => search(page - 1)}
                disabled={page === 0 || loading}
                className="px-3 py-1 text-xs border border-slate-200 rounded-lg disabled:opacity-40 hover:border-primary-400"
              >上一页</button>
              <button
                onClick={() => search(page + 1)}
                disabled={page >= totalPages - 1 || loading}
                className="px-3 py-1 text-xs border border-slate-200 rounded-lg disabled:opacity-40 hover:border-primary-400"
              >下一页</button>
            </div>
          )}
        </>
      )}

      {!data && !loading && (
        <div className="bg-white border border-slate-200 rounded-xl p-10 text-center text-slate-400 text-sm">
          设置筛选条件后点击"查询"
        </div>
      )}
    </div>
  )
}
