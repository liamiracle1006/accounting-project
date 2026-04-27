import { useState } from 'react'
import { reportsApi } from '@/api/reports'
import { useToast } from '@/hooks/useToast'
import { Spinner } from '@/components/common/Spinner'

const fmt = (n: number) => n.toLocaleString('zh-CN', { minimumFractionDigits: 2 })

export default function ReportsPage() {
  const now = new Date()
  const [year, setYear] = useState(now.getFullYear())
  const [month, setMonth] = useState(now.getMonth() + 1)
  const [data, setData] = useState<{ items: { account_name?: string; line_code?: string; balance?: number; debit?: number; credit?: number }[] } | null>(null)
  const [loading, setLoading] = useState(false)
  const [tab, setTab] = useState<'ie' | 'tb'>('ie')
  const { error } = useToast()

  const firstDay = `${year}-${String(month).padStart(2,'0')}-01`
  const lastDay  = new Date(year, month, 0).toISOString().slice(0, 10)

  const load = async () => {
    setLoading(true)
    try {
      if (tab === 'ie') setData(await reportsApi.incomeExpense(year, month) as typeof data)
      else              setData(await reportsApi.trialBalance(firstDay, lastDay) as typeof data)
    } catch (e) { error((e as Error).message) }
    finally { setLoading(false) }
  }

  return (
    <div className="p-6 max-w-4xl">
      <h1 className="text-xl font-bold text-slate-800 mb-5">财务报表</h1>
      <div className="flex gap-1 border-b border-slate-200 mb-5">
        {([['ie', '收支报表'], ['tb', '试算平衡表']] as [typeof tab, string][]).map(([key, label]) => (
          <button key={key} onClick={() => setTab(key)}
            className={`px-4 py-2 text-sm border-b-2 transition-colors ${tab === key ? 'border-primary-600 text-primary-700 font-medium' : 'border-transparent text-slate-500'}`}>
            {label}
          </button>
        ))}
      </div>
      <div className="flex gap-3 items-end mb-5">
        <div><label className="text-xs text-slate-500 block mb-1">年</label>
          <input type="number" value={year} onChange={e => setYear(+e.target.value)} className="border border-slate-200 rounded-lg px-3 py-2 text-sm w-20 focus:outline-none focus:ring-2 focus:ring-primary-500" /></div>
        <div><label className="text-xs text-slate-500 block mb-1">月</label>
          <input type="number" min={1} max={12} value={month} onChange={e => setMonth(+e.target.value)} className="border border-slate-200 rounded-lg px-3 py-2 text-sm w-16 focus:outline-none focus:ring-2 focus:ring-primary-500" /></div>
        <button onClick={load} disabled={loading} className="px-4 py-2 bg-primary-600 hover:bg-primary-700 disabled:bg-slate-300 text-white text-sm rounded-lg">
          {loading ? <Spinner size="sm" /> : '查询'}
        </button>
      </div>
      {data && (
        <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
          <table className="w-full text-sm"><thead className="bg-slate-50"><tr className="text-xs text-slate-500">
            <th className="px-4 py-3 text-left">科目</th>
            {tab === 'ie' ? <th className="px-4 py-3 text-right">金额</th>
              : <><th className="px-4 py-3 text-right">借方</th><th className="px-4 py-3 text-right">贷方</th></>}
          </tr></thead><tbody>
            {data.items.map((row, i) => (
              <tr key={i} className="border-t border-slate-100">
                <td className="px-4 py-2.5">{row.account_name ?? row.line_code}</td>
                {tab === 'ie'
                  ? <td className="px-4 py-2.5 text-right font-mono">¥{fmt(row.balance ?? 0)}</td>
                  : <><td className="px-4 py-2.5 text-right font-mono">¥{fmt(row.debit ?? 0)}</td>
                     <td className="px-4 py-2.5 text-right font-mono">¥{fmt(row.credit ?? 0)}</td></>}
              </tr>
            ))}
          </tbody></table>
        </div>
      )}
    </div>
  )
}
