import { useState, useEffect } from 'react'
import { api } from '@/api/client'
import { useToast } from '@/hooks/useToast'
import { PageLoader } from '@/components/common/Spinner'
import type { StatsSummary } from '@/types'

const fmt = (n: number) => n.toLocaleString('zh-CN', { minimumFractionDigits: 2 })

interface HealthRatio {
  name: string
  value: number
  unit: string
  rating: 'GOOD' | 'WARNING' | 'DANGER'
  description: string
  benchmark: string
}

interface HealthResponse {
  overall: 'GOOD' | 'WARNING' | 'DANGER'
  ratios: HealthRatio[]
  snapshot: { assets: number; liabilities: number; cash: number; profit: number; revenue: number }
}

interface Alert {
  level: 'DANGER' | 'WARNING' | 'INFO'
  category: string
  title: string
  detail: string
  action: string
}

const RATING_COLOR: Record<string, string> = {
  GOOD:    'text-green-600 bg-green-50 border-green-200',
  WARNING: 'text-amber-600 bg-amber-50 border-amber-200',
  DANGER:  'text-red-600 bg-red-50 border-red-200',
}

const ALERT_COLOR: Record<string, string> = {
  DANGER:  'border-l-red-500 bg-red-50',
  WARNING: 'border-l-amber-500 bg-amber-50',
  INFO:    'border-l-blue-500 bg-blue-50',
}

const ALERT_DOT: Record<string, string> = {
  DANGER:  'bg-red-500',
  WARNING: 'bg-amber-500',
  INFO:    'bg-blue-500',
}

const now = new Date()
const THIS_YEAR = now.getFullYear()
const YEARS = Array.from({ length: THIS_YEAR - 2019 }, (_, i) => 2020 + i)
const MONTHS = Array.from({ length: 12 }, (_, i) => i + 1)

export default function DashboardPage() {
  const [year,  setYear]  = useState(THIS_YEAR)
  const [month, setMonth] = useState(now.getMonth() + 1)
  const [stats,  setStats]  = useState<StatsSummary | null>(null)
  const [health, setHealth] = useState<HealthResponse | null>(null)
  const [alerts, setAlerts] = useState<Alert[]>([])
  const [loadingStats,  setLoadingStats]  = useState(true)
  const [loadingHealth, setLoadingHealth] = useState(true)
  const { error } = useToast()

  useEffect(() => {
    setLoadingStats(true)
    api.get<StatsSummary>(`/api/stats/summary?year=${year}&month=${month}`)
      .then(setStats)
      .catch(e => error((e as Error).message))
      .finally(() => setLoadingStats(false))
  }, [year, month])  // eslint-disable-line

  useEffect(() => {
    setLoadingHealth(true)
    Promise.all([
      api.get<HealthResponse>('/api/analytics/health'),
      api.get<Alert[]>('/api/analytics/alerts'),
    ]).then(([h, a]) => { setHealth(h); setAlerts(a) })
      .catch(e => error((e as Error).message))
      .finally(() => setLoadingHealth(false))
  }, [])  // eslint-disable-line

  const statCards = [
    { label: '本月收入',  value: stats?.total_income   ?? 0, color: 'text-green-600' },
    { label: '本月支出',  value: stats?.total_expense  ?? 0, color: 'text-red-500' },
    { label: '本月净利润', value: stats?.net_profit    ?? 0, color: 'text-primary-600' },
    { label: '凭证总数',  value: stats?.total_vouchers ?? 0, color: 'text-slate-700',  isCount: true },
    { label: '待审核',    value: stats?.pending_review ?? 0, color: 'text-amber-600',  isCount: true },
  ]

  return (
    <div className="p-6">
      {/* Header with period selector */}
      <div className="flex items-center justify-between mb-5">
        <h1 className="text-xl font-bold text-slate-800">仪表盘</h1>
        <div className="flex items-center gap-2 text-sm">
          <select value={year} onChange={e => setYear(Number(e.target.value))}
            className="border border-slate-200 rounded-lg px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500">
            {YEARS.map(y => <option key={y} value={y}>{y} 年</option>)}
          </select>
          <select value={month} onChange={e => setMonth(Number(e.target.value))}
            className="border border-slate-200 rounded-lg px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500">
            {MONTHS.map(m => <option key={m} value={m}>{m} 月</option>)}
          </select>
        </div>
      </div>

      {/* Stats cards */}
      {loadingStats ? <PageLoader /> : (
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-4 mb-6">
          {statCards.map(c => (
            <div key={c.label} className="bg-white border border-slate-200 rounded-xl p-4">
              <p className="text-xs text-slate-400 mb-1">{c.label}</p>
              <p className={`text-xl font-bold ${c.color}`}>
                {c.isCount ? c.value : `¥${fmt(c.value)}`}
              </p>
            </div>
          ))}
        </div>
      )}

      {loadingHealth ? (
        <div className="py-8 text-center text-sm text-slate-400">加载健康指标…</div>
      ) : (
        <>
          {/* Financial health */}
          <div className="mb-6">
            <div className="flex items-center gap-2 mb-3">
              <h2 className="text-sm font-semibold text-slate-700">财务健康指标</h2>
              {health && (
                <span className={`text-xs px-2 py-0.5 rounded-full border font-medium ${RATING_COLOR[health.overall]}`}>
                  {health.overall === 'GOOD' ? '良好' : health.overall === 'WARNING' ? '警告' : '危险'}
                </span>
              )}
            </div>
            <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
              {(health?.ratios ?? []).map(r => (
                <div key={r.name} className={`border rounded-xl p-4 ${RATING_COLOR[r.rating]}`}>
                  <p className="text-xs font-medium mb-1">{r.name}</p>
                  <p className="text-lg font-bold">{r.value != null ? r.value.toFixed(2) : '—'}{r.unit}</p>
                  <p className="text-xs mt-1 opacity-70">基准：{r.benchmark}</p>
                  <p className="text-xs mt-0.5 opacity-60 line-clamp-2">{r.description}</p>
                </div>
              ))}
            </div>
          </div>

          {/* Alerts */}
          {alerts.length > 0 && (
            <div>
              <h2 className="text-sm font-semibold text-slate-700 mb-3">智能提醒</h2>
              <div className="space-y-2">
                {alerts.map((a, i) => (
                  <div key={i} className={`border-l-4 rounded-r-xl p-4 ${ALERT_COLOR[a.level]}`}>
                    <div className="flex items-center gap-2 mb-1">
                      <span className={`w-2 h-2 rounded-full flex-shrink-0 ${ALERT_DOT[a.level]}`} />
                      <span className="text-sm font-medium text-slate-800">{a.title}</span>
                      <span className="text-xs text-slate-400 ml-auto">{a.category}</span>
                    </div>
                    <p className="text-xs text-slate-600 ml-4">{a.detail}</p>
                    {a.action && <p className="text-xs text-slate-500 ml-4 mt-1">建议：{a.action}</p>}
                  </div>
                ))}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}
