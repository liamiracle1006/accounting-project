import { useState, useEffect, useCallback } from 'react'
import { periodsApi } from '@/api/periods'
import { useToast } from '@/hooks/useToast'
import { PageLoader } from '@/components/common/Spinner'
import type { AccountingPeriod } from '@/types'

export default function PeriodClosingPage() {
  const [periods, setPeriods] = useState<AccountingPeriod[]>([])
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const { success, error } = useToast()

  const load = useCallback(async () => {
    try {
      setPeriods(await periodsApi.list())
    } catch (e) {
      error((e as Error).message)
    } finally {
      setLoading(false)
    }
  }, [error])

  useEffect(() => { load() }, [load])

  const latestClosedIdx = [...periods].findIndex(p => p.status === 'CLOSED')

  const handleClose = async (p: AccountingPeriod) => {
    setBusy(true)
    try {
      const r = await periodsApi.close(p.year, p.month)
      success(`✅ ${r.message}，下期：${r.next_period_year}/${r.next_period_month}，整理 ${r.reorganized_count} 条`)
      load()
    } catch (e) { error((e as Error).message) }
    finally { setBusy(false) }
  }

  const handleTransferPnL = async (p: AccountingPeriod) => {
    setBusy(true)
    try {
      const r = await periodsApi.transferPnL(p.year, p.month)
      success(`✅ 结转损益完成，净利润 ¥${r.net_profit.toLocaleString()}，凭证 #${r.voucher_id}`)
      load()
    } catch (e) { error((e as Error).message) }
    finally { setBusy(false) }
  }

  const handleUnclose = async (p: AccountingPeriod) => {
    setBusy(true)
    try {
      const r = await periodsApi.unclose(p.year, p.month)
      success(r.message)
      load()
    } catch (e) { error((e as Error).message) }
    finally { setBusy(false) }
  }

  if (loading) return <PageLoader />

  return (
    <div className="p-6 max-w-3xl">
      <h1 className="text-xl font-bold text-slate-800 mb-5">月末结账</h1>

      <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-slate-50">
            <tr className="text-xs text-slate-500">
              <th className="px-5 py-3 text-left">账期</th>
              <th className="px-5 py-3 text-center">状态</th>
              <th className="px-5 py-3 text-right">操作</th>
            </tr>
          </thead>
          <tbody>
            {periods.length === 0 && (
              <tr><td colSpan={3} className="px-5 py-8 text-center text-slate-400">暂无账期数据</td></tr>
            )}
            {periods.map((p, idx) => (
              <tr key={`${p.year}-${p.month}`} className="border-t border-slate-100">
                <td className="px-5 py-3 font-medium">
                  {p.year} 年 {String(p.month).padStart(2, '0')} 月
                </td>
                <td className="px-5 py-3 text-center">
                  <span className={`inline-flex items-center gap-1 text-xs font-semibold ${p.status === 'CLOSED' ? 'text-slate-500' : 'text-green-600'}`}>
                    <span className="w-1.5 h-1.5 rounded-full inline-block" style={{ background: p.status === 'CLOSED' ? '#94a3b8' : '#16a34a' }} />
                    {p.status === 'CLOSED' ? '已结账' : '开放中'}
                  </span>
                </td>
                <td className="px-5 py-3 text-right space-x-2">
                  {p.status === 'OPEN' && (
                    <>
                      <button disabled={busy} onClick={() => handleTransferPnL(p)}
                        className="text-xs px-3 py-1.5 border border-violet-400 text-violet-600 rounded-lg hover:bg-violet-50 disabled:opacity-50">
                        结转损益
                      </button>
                      <button disabled={busy} onClick={() => handleClose(p)}
                        className="text-xs px-3 py-1.5 bg-primary-600 hover:bg-primary-700 text-white rounded-lg disabled:opacity-50">
                        执行月末结账
                      </button>
                    </>
                  )}
                  {p.status === 'CLOSED' && idx === latestClosedIdx && (
                    <button disabled={busy} onClick={() => handleUnclose(p)}
                      className="text-xs px-3 py-1.5 border border-amber-400 text-amber-600 rounded-lg hover:bg-amber-50 disabled:opacity-50">
                      反结账
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
