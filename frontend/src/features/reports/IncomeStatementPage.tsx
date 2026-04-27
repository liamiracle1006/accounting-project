import { useEffect, useState, useCallback } from 'react'
import { reportsApi } from '@/api/reports'
import type { IncomeStatement, ISLineItem } from '@/types'

// ── Helpers ───────────────────────────────────────────────────────────────────

function firstDayOfMonth(year: number, month: number): string {
  return `${year}-${String(month).padStart(2, '0')}-01`
}

function lastDayOfMonth(year: number, month: number): string {
  const d = new Date(year, month, 0)
  return `${year}-${String(month).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

function fmt(n: number, isTotal: boolean): string {
  if (!isTotal && n === 0) return '—'
  return n.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

function rowStyle(item: ISLineItem): string {
  if (item.name.startsWith('四、') || item.name.includes('净利润') && item.is_total)
    return 'bg-green-50 font-bold text-green-800'
  if (item.is_total)
    return 'bg-gray-50 font-semibold text-gray-700'
  return 'hover:bg-blue-50/30 transition-colors'
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function IncomeStatementPage() {
  const today     = new Date()
  const [year,     setYear]     = useState(today.getFullYear())
  const [month,    setMonth]    = useState(today.getMonth() + 1)
  const [standard, setStandard] = useState<'gaap' | 'xiye'>('gaap')
  const [data,    setData]    = useState<IncomeStatement | null>(null)
  const [loading, setLoading] = useState(false)
  const [error,   setError]   = useState<string | null>(null)

  const fetchData = useCallback(() => {
    const from = firstDayOfMonth(year, month)
    const to   = lastDayOfMonth(year, month)
    setLoading(true)
    setError(null)
    reportsApi.incomeStatement(from, to, standard)
      .then(d  => setData(d))
      .catch(() => setError('加载失败，请检查后端服务'))
      .finally(() => setLoading(false))
  }, [year, month, standard])

  useEffect(() => { fetchData() }, [fetchData])

  return (
    <div className="flex flex-col h-full gap-3 p-4 overflow-hidden">

      {/* Toolbar */}
      <div className="bg-white rounded-xl border border-gray-200 px-4 py-3 flex flex-wrap items-end gap-3 shrink-0 print:hidden">
        <div className="flex flex-col gap-1">
          <label className="text-xs text-gray-500">年份</label>
          <input
            type="number"
            value={year}
            min={2000}
            max={2099}
            onChange={e => setYear(Number(e.target.value))}
            className="border border-gray-200 rounded px-2 py-1.5 text-sm w-24 focus:outline-none focus:ring-1 focus:ring-blue-400"
          />
        </div>
        <div className="flex flex-col gap-1">
          <label className="text-xs text-gray-500">月份</label>
          <select
            value={month}
            onChange={e => setMonth(Number(e.target.value))}
            className="border border-gray-200 rounded px-2 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-blue-400"
          >
            {Array.from({ length: 12 }, (_, i) => i + 1).map(m => (
              <option key={m} value={m}>{m} 月</option>
            ))}
          </select>
        </div>
        <div className="flex flex-col gap-1">
          <label className="text-xs text-gray-500">会计准则</label>
          <div className="flex gap-3 items-center h-8">
            {(['gaap', 'xiye'] as const).map(s => (
              <label key={s} className="flex items-center gap-1.5 cursor-pointer text-sm text-gray-700">
                <input
                  type="radio"
                  name="is-standard"
                  value={s}
                  checked={standard === s}
                  onChange={() => setStandard(s)}
                  className="accent-blue-600"
                />
                {s === 'gaap' ? '企业准则' : '小企业准则'}
              </label>
            ))}
          </div>
        </div>
        <button
          onClick={fetchData}
          disabled={loading}
          className="px-4 py-1.5 rounded bg-blue-600 text-white text-sm font-medium hover:bg-blue-700 transition-colors disabled:opacity-50"
        >
          {loading ? '计算中…' : '查询'}
        </button>
        <button
          onClick={() => window.print()}
          className="px-4 py-1.5 rounded border border-gray-300 text-sm text-gray-600 hover:bg-gray-50 transition-colors"
        >
          打印
        </button>
        {data && (
          <span className="text-xs text-gray-400 ml-2">
            本期 {data.date_from} ~ {data.date_to}　上期 {data.prev_from} ~ {data.prev_to}
          </span>
        )}
      </div>

      {/* Title */}
      <div className="text-center shrink-0 print:block">
        <h2 className="text-base font-bold text-gray-800">利润表（会企02表）</h2>
        {data && (
          <p className="text-xs text-gray-500 mt-0.5">
            编制单位：本账套　　报告期间：{data.date_from} 至 {data.date_to}　　单位：元
          </p>
        )}
      </div>

      {/* Error */}
      {error && (
        <div className="bg-red-50 border border-red-300 text-red-700 text-sm rounded-lg px-4 py-3 shrink-0">
          {error}
        </div>
      )}

      {/* Table */}
      {data && !loading && (() => {
        const hasRowNum = data.items.some(i => i.row_num > 0)
        return (
          <div className="bg-white rounded-xl border border-gray-200 overflow-auto flex-1">
            <table className="w-full text-sm border-collapse">
              <thead>
                <tr className="bg-gray-50 sticky top-0 z-10">
                  {hasRowNum && (
                    <th className="border border-gray-200 px-2 py-2 text-center font-medium text-gray-600 w-10">行次</th>
                  )}
                  <th className="border border-gray-200 px-3 py-2 text-left font-medium text-gray-600 w-[50%]">
                    项目
                  </th>
                  <th className="border border-gray-200 px-3 py-2 text-right font-medium text-gray-600 w-[25%]">
                    {data.col1_label ?? '本期金额'}
                  </th>
                  <th className="border border-gray-200 px-3 py-2 text-right font-medium text-gray-600 w-[25%]">
                    {data.col2_label ?? '上期金额'}
                  </th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((item, idx) => (
                  <ISRow key={idx} item={item} hasRowNum={hasRowNum} />
                ))}
              </tbody>
            </table>
          </div>
        )
      })()}

      {loading && !data && (
        <div className="flex-1 flex items-center justify-center text-gray-400 text-sm">
          计算中…
        </div>
      )}
    </div>
  )
}

// ── Row ───────────────────────────────────────────────────────────────────────

function ISRow({ item, hasRowNum }: { item: ISLineItem; hasRowNum: boolean }) {
  const bg = rowStyle(item)
  const isReduce = item.name.startsWith('减：') || item.name.startsWith('加：')
  const indent = !item.is_total && isReduce ? 'pl-6' : 'pl-3'

  return (
    <tr className={bg}>
      {hasRowNum && (
        <td className="border border-gray-200 px-2 py-1.5 text-center text-gray-400 text-xs">
          {item.row_num > 0 ? item.row_num : ''}
        </td>
      )}
      <td className={`border border-gray-200 px-3 py-1.5 text-gray-700 ${indent}`}>
        {item.name}
      </td>
      <td className={`border border-gray-200 px-3 py-1.5 text-right tabular-nums ${item.cur_amt < 0 ? 'text-red-600' : 'text-gray-800'}`}>
        {fmt(item.cur_amt, item.is_total)}
      </td>
      <td className={`border border-gray-200 px-3 py-1.5 text-right tabular-nums ${item.prev_amt < 0 ? 'text-red-600' : 'text-gray-800'}`}>
        {fmt(item.prev_amt, item.is_total)}
      </td>
    </tr>
  )
}
