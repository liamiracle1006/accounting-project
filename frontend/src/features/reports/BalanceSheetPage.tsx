import { useEffect, useState, useCallback } from 'react'
import { reportsApi } from '@/api/reports'
import type { BalanceSheet, BSLineItem } from '@/types'

// ── Helpers ───────────────────────────────────────────────────────────────────

function lastDayOfMonth(year: number, month: number): string {
  const d = new Date(year, month, 0) // day 0 = last day of previous month
  return `${year}-${String(month).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

function fmt(n: number): string {
  if (n === 0) return '—'
  return n.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

function fmtTotal(n: number): string {
  return n.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

// ── Sub-components ────────────────────────────────────────────────────────────

function SectionTable({
  title,
  items,
  colClass = '',
}: {
  title: string
  items: BSLineItem[]
  colClass?: string
}) {
  return (
    <div className={`flex-1 min-w-0 ${colClass}`}>
      <table className="w-full text-sm border-collapse">
        <thead>
          <tr className="bg-gray-50">
            <th className="border border-gray-200 px-3 py-2 text-left font-medium text-gray-600 w-[45%]">
              {title}
            </th>
            <th className="border border-gray-200 px-3 py-2 text-right font-medium text-gray-600 w-[27.5%]">
              期末余额
            </th>
            <th className="border border-gray-200 px-3 py-2 text-right font-medium text-gray-600 w-[27.5%]">
              年初余额
            </th>
          </tr>
        </thead>
        <tbody>
          {items.map((item, idx) => (
            <tr
              key={idx}
              className={
                item.is_total
                  ? 'bg-gray-50 font-semibold'
                  : 'hover:bg-blue-50/30 transition-colors'
              }
            >
              <td className={`border border-gray-200 px-3 py-1.5 text-gray-700 ${item.is_total ? '' : 'pl-5'}`}>
                {item.name}
              </td>
              <td className="border border-gray-200 px-3 py-1.5 text-right tabular-nums text-gray-800">
                {item.is_total ? fmtTotal(item.end_bal) : fmt(item.end_bal)}
              </td>
              <td className="border border-gray-200 px-3 py-1.5 text-right tabular-nums text-gray-800">
                {item.is_total ? fmtTotal(item.beg_bal) : fmt(item.beg_bal)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function BalanceSheetPage() {
  const today     = new Date()
  const [year,  setYear]  = useState(today.getFullYear())
  const [month, setMonth] = useState(today.getMonth() + 1)
  const [data,    setData]    = useState<BalanceSheet | null>(null)
  const [loading, setLoading] = useState(false)
  const [error,   setError]   = useState<string | null>(null)

  const fetchData = useCallback(() => {
    const asOf = lastDayOfMonth(year, month)
    setLoading(true)
    setError(null)
    reportsApi.balanceSheet(asOf)
      .then(d  => setData(d))
      .catch(() => setError('加载失败，请检查后端服务'))
      .finally(() => setLoading(false))
  }, [year, month])

  useEffect(() => { fetchData() }, [fetchData])

  const liabAndEquity = data ? [...data.liabilities, ...data.equity] : []

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
            截至 {data.as_of_date}，年初 {data.beg_of_year}
          </span>
        )}
      </div>

      {/* Title */}
      <div className="text-center shrink-0 print:block">
        <h2 className="text-base font-bold text-gray-800">资产负债表（会企01表）</h2>
        {data && (
          <p className="text-xs text-gray-500 mt-0.5">编制单位：本账套　　报告日期：{data.as_of_date}　　单位：元</p>
        )}
      </div>

      {/* Error */}
      {error && (
        <div className="bg-red-50 border border-red-300 text-red-700 text-sm rounded-lg px-4 py-3 shrink-0">
          {error}
        </div>
      )}

      {/* Unbalanced warning */}
      {data && !data.balanced && (
        <div className="bg-red-50 border border-red-400 text-red-800 text-sm rounded-lg px-4 py-3 shrink-0 font-medium">
          ⚠️ 报表试算不平衡（资产合计 ≠ 负债及所有者权益合计，差额 {fmtTotal(Math.abs(data.diff))} 元），请检查是否存在未结转的损益或公式配置错误
        </div>
      )}

      {/* Tables */}
      {data && !loading && (
        <div className="bg-white rounded-xl border border-gray-200 overflow-auto flex-1">
          <div className="flex gap-0 min-w-[900px]">
            <SectionTable title="资产" items={data.assets} />
            <div className="w-px bg-gray-300 shrink-0" />
            <SectionTable title="负债及所有者权益" items={liabAndEquity} />
          </div>
        </div>
      )}

      {loading && !data && (
        <div className="flex-1 flex items-center justify-center text-gray-400 text-sm">
          计算中…
        </div>
      )}
    </div>
  )
}
