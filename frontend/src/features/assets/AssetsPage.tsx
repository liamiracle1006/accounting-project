import { useState, useEffect } from 'react'
import { assetsApi } from '@/api/assets'
import { useToast } from '@/hooks/useToast'
import { PageLoader } from '@/components/common/Spinner'
import type { Asset } from '@/types'

const fmt = (n: number) => n.toLocaleString('zh-CN', { minimumFractionDigits: 2 })

const STATUS_OPTIONS = [
  { value: '',                   label: '全部状态' },
  { value: 'IN_USE',             label: '在用' },
  { value: 'FULLY_DEPRECIATED',  label: '已提足折旧' },
  { value: 'DISPOSED',           label: '已处置' },
]

const STATUS_LABEL: Record<string, string> = {
  IN_USE:            '在用',
  FULLY_DEPRECIATED: '已提足折旧',
  DISPOSED:          '已处置',
}

export default function AssetsPage() {
  const [assets, setAssets]           = useState<Asset[]>([])
  const [loading, setLoading]         = useState(true)
  const [statusFilter, setStatusFilter] = useState('')
  const { success, error } = useToast()
  const now = new Date()

  useEffect(() => {
    assetsApi.list().then(setAssets).catch(e => error((e as Error).message)).finally(() => setLoading(false))
  }, [])  // eslint-disable-line

  const runDepreciation = async () => {
    try {
      await assetsApi.runDepreciation(now.getFullYear(), now.getMonth() + 1)
      success('折旧计算完成')
    } catch (e) { error((e as Error).message) }
  }

  if (loading) return <PageLoader />

  const visible = statusFilter ? assets.filter(a => a.status === statusFilter) : assets

  const totalOriginal  = visible.reduce((s, a) => s + a.original_value, 0)
  const totalNet       = visible.reduce((s, a) => s + a.net_book_value, 0)
  const totalMonthlyDep = visible.reduce((s, a) => s + ((a as any).monthly_depreciation ?? 0), 0)
  const hasDepField    = assets.some(a => (a as any).monthly_depreciation !== undefined)

  const summaryCards = [
    { label: '资产数量',     value: `${visible.length} 项`, color: 'text-slate-700' },
    { label: '原值合计',     value: `¥${fmt(totalOriginal)}`, color: 'text-primary-600' },
    { label: '账面净值合计', value: `¥${fmt(totalNet)}`, color: 'text-green-600' },
    { label: '本月折旧额',   value: hasDepField ? `¥${fmt(totalMonthlyDep)}` : '—', color: 'text-amber-600' },
  ]

  return (
    <div className="p-6 max-w-4xl">
      <div className="flex items-center justify-between mb-5">
        <h1 className="text-xl font-bold text-slate-800">固定资产</h1>
        <button onClick={runDepreciation} className="px-3 py-1.5 border border-primary-400 text-primary-600 text-xs rounded-lg hover:bg-primary-50 font-medium">
          运行本月折旧
        </button>
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-4 gap-3 mb-5">
        {summaryCards.map(c => (
          <div key={c.label} className="bg-white border border-slate-200 rounded-xl p-4">
            <p className="text-xs text-slate-400 mb-1">{c.label}</p>
            <p className={`text-base font-bold ${c.color}`}>{c.value}</p>
          </div>
        ))}
      </div>

      {/* Status filter */}
      <div className="flex items-center gap-3 mb-3">
        <span className="text-xs text-slate-500">状态筛选：</span>
        <select
          value={statusFilter}
          onChange={e => setStatusFilter(e.target.value)}
          className="border border-slate-200 rounded-lg px-2 py-1 text-xs focus:outline-none focus:ring-2 focus:ring-primary-500"
        >
          {STATUS_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
        </select>
      </div>

      <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
        <table className="w-full text-sm"><thead className="bg-slate-50"><tr className="text-xs text-slate-500">
          <th className="px-4 py-3 text-left">资产名称</th><th className="px-4 py-3 text-right">原值</th>
          <th className="px-4 py-3 text-right">账面净值</th><th className="px-4 py-3 text-center">状态</th><th className="px-4 py-3 text-left">购入日期</th>
        </tr></thead><tbody>
          {visible.length === 0 && <tr><td colSpan={5} className="px-4 py-10 text-center text-slate-400">暂无固定资产</td></tr>}
          {visible.map(a => (
            <tr key={a.asset_id} className="border-t border-slate-100">
              <td className="px-4 py-3 font-medium">{a.name}</td>
              <td className="px-4 py-3 text-right font-mono">¥{fmt(a.original_value)}</td>
              <td className="px-4 py-3 text-right font-mono">¥{fmt(a.net_book_value)}</td>
              <td className="px-4 py-3 text-center">
                <span className="text-xs text-slate-600">{STATUS_LABEL[a.status] ?? a.status}</span>
              </td>
              <td className="px-4 py-3 text-xs text-slate-400">{a.purchase_date}</td>
            </tr>
          ))}
        </tbody></table>
      </div>
    </div>
  )
}
