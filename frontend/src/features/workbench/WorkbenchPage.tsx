import { useState, useEffect, useCallback } from 'react'
import { workbenchApi } from '@/api/workbench'
import { useToast } from '@/hooks/useToast'
import { ReviewStatusBadge } from '@/components/common/Badge'
import { Modal } from '@/components/common/Modal'
import { PageLoader } from '@/components/common/Spinner'
import type { WorkbenchVoucher } from '@/types'

const fmt = (n: number) => n.toLocaleString('zh-CN', { minimumFractionDigits: 2 })

export default function WorkbenchPage() {
  const [filter, setFilter] = useState('')
  const [vouchers, setVouchers] = useState<WorkbenchVoucher[]>([])
  const [loading, setLoading] = useState(true)
  const [selected, setSelected] = useState<WorkbenchVoucher | null>(null)
  const [detailOpen, setDetailOpen] = useState(false)
  const { success, error } = useToast()

  const load = useCallback(async () => {
    setLoading(true)
    try { setVouchers(await workbenchApi.list(filter || undefined)) }
    catch (e) { error((e as Error).message) }
    finally { setLoading(false) }
  }, [filter, error])

  useEffect(() => { load() }, [load])

  const openDetail = async (v: WorkbenchVoucher) => {
    const full = await workbenchApi.get(v.voucher_id)
    setSelected(full); setDetailOpen(true)
  }

  const handleAction = async (action: 'submit' | 'post' | 'reject') => {
    if (!selected) return
    try {
      if (action === 'submit') await workbenchApi.submit(selected.voucher_id)
      else if (action === 'post') await workbenchApi.post(selected.voucher_id)
      else await workbenchApi.reject(selected.voucher_id)
      success('操作成功')
      setDetailOpen(false); load()
    } catch (e) { error((e as Error).message) }
  }

  const filters: [string, string][] = [['', '全部'], ['PENDING_REVIEW', '待审核'], ['POSTED', '已过账'], ['DRAFT', '草稿']]

  if (loading) return <PageLoader />

  return (
    <div className="p-6 max-w-5xl">
      <h1 className="text-xl font-bold text-slate-800 mb-5">财务工作台</h1>
      <div className="flex gap-1 border-b border-slate-200 mb-4">
        {filters.map(([key, label]) => (
          <button key={key} onClick={() => setFilter(key)}
            className={`px-4 py-2 text-sm border-b-2 transition-colors ${filter === key ? 'border-primary-600 text-primary-700 font-medium' : 'border-transparent text-slate-500 hover:text-slate-700'}`}>
            {label}
          </button>
        ))}
      </div>
      <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-slate-50"><tr className="text-xs text-slate-500">
            <th className="px-4 py-3 text-left">日期</th>
            <th className="px-4 py-3 text-left">摘要</th>
            <th className="px-4 py-3 text-right">借方金额</th>
            <th className="px-4 py-3 text-center">状态</th>
          </tr></thead>
          <tbody>
            {vouchers.length === 0 && <tr><td colSpan={4} className="px-4 py-10 text-center text-slate-400">暂无数据</td></tr>}
            {vouchers.map(v => (
              <tr key={v.voucher_id} onClick={() => openDetail(v)}
                className="border-t border-slate-100 hover:bg-slate-50/50 cursor-pointer">
                <td className="px-4 py-3 text-slate-500">{v.voucher_date}</td>
                <td className="px-4 py-3 truncate max-w-xs">{v.description}</td>
                <td className="px-4 py-3 text-right font-mono">¥{fmt(v.total_debit)}</td>
                <td className="px-4 py-3 text-center"><ReviewStatusBadge status={v.review_status} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Modal open={detailOpen} onClose={() => setDetailOpen(false)} title="凭证详情" width="max-w-2xl"
        footer={selected && (
          <>
            {selected.review_status === 'DRAFT' && (
              <button onClick={() => handleAction('submit')} className="px-3 py-1.5 text-sm bg-primary-600 text-white rounded-lg">提交审核</button>
            )}
            {selected.review_status === 'PENDING_REVIEW' && (
              <>
                <button onClick={() => handleAction('reject')} className="px-3 py-1.5 text-sm border border-red-400 text-red-600 rounded-lg">驳回</button>
                <button onClick={() => handleAction('post')} className="px-3 py-1.5 text-sm bg-green-600 text-white rounded-lg">过账</button>
              </>
            )}
          </>
        )}>
        {selected && (
          <div>
            <div className="grid grid-cols-2 gap-2 mb-4 text-sm text-slate-600">
              <div>日期：{selected.voucher_date}</div>
              <div>状态：<ReviewStatusBadge status={selected.review_status} /></div>
              <div className="col-span-2">摘要：{selected.description}</div>
            </div>
            <table className="w-full text-xs"><thead className="bg-slate-50"><tr className="text-slate-500">
              <th className="px-3 py-2 text-left">科目</th><th className="px-3 py-2 text-center">方向</th><th className="px-3 py-2 text-right">金额</th>
            </tr></thead><tbody>
              {selected.lines.map((l, i) => (
                <tr key={i} className="border-t border-slate-100">
                  <td className="px-3 py-1.5">{l.subject_code} {l.subject_name}</td>
                  <td className="px-3 py-1.5 text-center">{l.direction === 'DEBIT' ? '借' : '贷'}</td>
                  <td className="px-3 py-1.5 text-right font-mono">¥{fmt(l.amount)}</td>
                </tr>
              ))}
            </tbody></table>
          </div>
        )}
      </Modal>
    </div>
  )
}
