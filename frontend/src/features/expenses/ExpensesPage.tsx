import { useState, useEffect, useCallback } from 'react'
import { expensesApi } from '@/api/expenses'
import { useToast } from '@/hooks/useToast'
import { Badge } from '@/components/common/Badge'
import { Modal } from '@/components/common/Modal'
import { PageLoader } from '@/components/common/Spinner'
import type { ExpenseRequest } from '@/types'
import { useAuthStore, isBoss } from '@/store/useAuthStore'

const fmt = (n: number) => n.toLocaleString('zh-CN', { minimumFractionDigits: 2 })

export default function ExpensesPage() {
  const [expenses, setExpenses] = useState<ExpenseRequest[]>([])
  const [loading, setLoading] = useState(true)
  const [createOpen, setCreateOpen] = useState(false)
  const [title, setTitle] = useState(''); const [amount, setAmount] = useState('')
  const [expType, setExpType] = useState('GENERAL'); const [descTxt, setDescTxt] = useState('')
  const { success, error } = useToast()
  const { user } = useAuthStore()
  const boss = isBoss(user)

  const load = useCallback(async () => {
    try { setExpenses(await expensesApi.list()) }
    catch (e) { error((e as Error).message) }
    finally { setLoading(false) }
  }, [error])

  useEffect(() => { load() }, [load])

  const create = async () => {
    if (!title || !amount) { error('请填写标题和金额'); return }
    try {
      await expensesApi.create({ title, amount: parseFloat(amount), expense_type: expType, description: descTxt })
      success('申请已提交'); setCreateOpen(false); load()
    } catch (e) { error((e as Error).message) }
  }

  const act = async (id: number, action: 'approve' | 'reject') => {
    try {
      if (action === 'approve') await expensesApi.approve(id)
      else await expensesApi.reject(id)
      success('操作成功'); load()
    } catch (e) { error((e as Error).message) }
  }

  const statusBadge = (s: string) => {
    const m: Record<string, [string, 'green' | 'yellow' | 'red']> = {
      APPROVED: ['已批准', 'green'], REJECTED: ['已驳回', 'red'], PENDING: ['待审批', 'yellow']
    }
    const [l, v] = m[s] ?? [s, 'gray' as const]
    return <Badge variant={v}>{l}</Badge>
  }

  if (loading) return <PageLoader />

  return (
    <div className="p-6 max-w-4xl">
      <div className="flex items-center justify-between mb-5">
        <h1 className="text-xl font-bold text-slate-800">费用申请</h1>
        <button onClick={() => setCreateOpen(true)} className="px-3 py-1.5 bg-primary-600 text-white text-xs rounded-lg hover:bg-primary-700 font-medium">+ 新建申请</button>
      </div>
      <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
        <table className="w-full text-sm"><thead className="bg-slate-50"><tr className="text-xs text-slate-500">
          <th className="px-4 py-3 text-left">标题</th><th className="px-4 py-3 text-right">金额</th>
          <th className="px-4 py-3 text-center">状态</th><th className="px-4 py-3 text-left">日期</th><th className="px-4 py-3"></th>
        </tr></thead><tbody>
          {expenses.length === 0 && <tr><td colSpan={5} className="px-4 py-10 text-center text-slate-400">暂无费用申请</td></tr>}
          {expenses.map(e => (
            <tr key={e.request_id} className="border-t border-slate-100">
              <td className="px-4 py-3">{e.title}</td>
              <td className="px-4 py-3 text-right font-mono">¥{fmt(e.amount)}</td>
              <td className="px-4 py-3 text-center">{statusBadge(e.status)}</td>
              <td className="px-4 py-3 text-xs text-slate-400">{e.created_at.slice(0, 10)}</td>
              <td className="px-4 py-3 text-right">
                {boss && e.status === 'PENDING' && (
                  <span className="flex gap-2 justify-end">
                    <button onClick={() => act(e.request_id, 'approve')} className="text-xs text-green-600 hover:underline">批准</button>
                    <button onClick={() => act(e.request_id, 'reject')} className="text-xs text-red-500 hover:underline">驳回</button>
                  </span>
                )}
              </td>
            </tr>
          ))}
        </tbody></table>
      </div>

      <Modal open={createOpen} onClose={() => setCreateOpen(false)} title="新建费用申请"
        footer={<>
          <button onClick={() => setCreateOpen(false)} className="px-3 py-1.5 text-sm border border-slate-300 rounded-lg">取消</button>
          <button onClick={create} className="px-3 py-1.5 text-sm bg-primary-600 text-white rounded-lg">提交</button>
        </>}>
        <div className="space-y-3">
          <div><label className="text-xs text-slate-500 block mb-1">标题 *</label>
            <input value={title} onChange={e => setTitle(e.target.value)} className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500" /></div>
          <div><label className="text-xs text-slate-500 block mb-1">金额 *</label>
            <input type="number" value={amount} onChange={e => setAmount(e.target.value)} min="0.01" step="0.01" className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500" /></div>
          <div><label className="text-xs text-slate-500 block mb-1">类型</label>
            <select value={expType} onChange={e => setExpType(e.target.value)} className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm">
              {['GENERAL', 'TRAVEL', 'OFFICE', 'MEAL'].map(t => <option key={t}>{t}</option>)}
            </select></div>
          <div><label className="text-xs text-slate-500 block mb-1">说明</label>
            <textarea value={descTxt} onChange={e => setDescTxt(e.target.value)} rows={2} className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm resize-none focus:outline-none focus:ring-2 focus:ring-primary-500" /></div>
        </div>
      </Modal>
    </div>
  )
}
