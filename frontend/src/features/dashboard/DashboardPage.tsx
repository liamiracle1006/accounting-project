import { useState, useEffect } from 'react'
import { api } from '@/api/client'
import { useToast } from '@/hooks/useToast'
import { PageLoader } from '@/components/common/Spinner'
import type { StatsSummary } from '@/types'

const fmt = (n: number) => n.toLocaleString('zh-CN', { minimumFractionDigits: 2 })

export default function DashboardPage() {
  const [stats, setStats] = useState<StatsSummary | null>(null)
  const [loading, setLoading] = useState(true)
  const { error } = useToast()
  const now = new Date()

  useEffect(() => {
    api.get<StatsSummary>(`/api/stats/summary?year=${now.getFullYear()}&month=${now.getMonth() + 1}`)
      .then(setStats)
      .catch(e => error((e as Error).message))
      .finally(() => setLoading(false))
  }, [])  // eslint-disable-line

  if (loading) return <PageLoader />

  const cards = [
    { label: '本月收入', value: stats?.total_income ?? 0, color: 'text-green-600' },
    { label: '本月支出', value: stats?.total_expense ?? 0, color: 'text-red-500' },
    { label: '本月净利润', value: stats?.net_profit ?? 0, color: 'text-primary-600' },
    { label: '凭证总数', value: stats?.total_vouchers ?? 0, color: 'text-slate-700', isCount: true },
    { label: '待审核', value: stats?.pending_review ?? 0, color: 'text-amber-600', isCount: true },
  ]

  return (
    <div className="p-6">
      <h1 className="text-xl font-bold text-slate-800 mb-5">
        仪表盘 — {now.getFullYear()} 年 {now.getMonth() + 1} 月
      </h1>
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-4">
        {cards.map(c => (
          <div key={c.label} className="bg-white border border-slate-200 rounded-xl p-4">
            <p className="text-xs text-slate-400 mb-1">{c.label}</p>
            <p className={`text-xl font-bold ${c.color}`}>
              {c.isCount ? c.value : `¥${fmt(c.value)}`}
            </p>
          </div>
        ))}
      </div>
    </div>
  )
}
