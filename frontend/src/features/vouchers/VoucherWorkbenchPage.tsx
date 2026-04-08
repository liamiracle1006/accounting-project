import { useState, useEffect, useCallback } from 'react'
import { vouchersApi } from '@/api/vouchers'
import { workbenchApi } from '@/api/workbench'
import { useToast } from '@/hooks/useToast'
import { ReviewStatusBadge } from '@/components/common/Badge'
import { Modal } from '@/components/common/Modal'
import { ConfirmDialog } from '@/components/common/ConfirmDialog'
import { PageLoader } from '@/components/common/Spinner'
import type { VoucherOut } from '@/types'

const fmt = (n: number) => n.toLocaleString('zh-CN', { minimumFractionDigits: 2 })
type StatusFilter = 'ALL' | 'DRAFT' | 'PENDING_REVIEW' | 'POSTED'

export default function VoucherWorkbenchPage() {
  const [filter, setFilter] = useState<StatusFilter>('ALL')
  const [vouchers, setVouchers] = useState<VoucherOut[]>([])
  const [loading, setLoading] = useState(true)
  const [selected, setSelected] = useState<VoucherOut | null>(null)
  const [detailOpen, setDetailOpen] = useState(false)
  const [trashOpen, setTrashOpen] = useState(false)
  const [trashVouchers, setTrashVouchers] = useState<VoucherOut[]>([])
  const [reorgOpen, setReorgOpen] = useState(false)
  const [reorgYear, setReorgYear] = useState(new Date().getFullYear())
  const [reorgMonth, setReorgMonth] = useState(new Date().getMonth() + 1)
  const [deleteTarget, setDeleteTarget] = useState<number | null>(null)
  const { success, error } = useToast()

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const status = filter !== 'ALL' ? filter : undefined
      setVouchers(await vouchersApi.list(status ? { review_status: status } : undefined))
    } catch (e) {
      error((e as Error).message)
    } finally {
      setLoading(false)
    }
  }, [filter, error])

  useEffect(() => { load() }, [load])

  const openDetail = async (v: VoucherOut) => {
    const full = await vouchersApi.get(v.voucher_id)
    setSelected(full); setDetailOpen(true)
  }

  const handleAction = async (action: 'submit' | 'post' | 'reject', id: number) => {
    try {
      if (action === 'submit') await workbenchApi.submit(id)
      else if (action === 'post') await workbenchApi.post(id)
      else await workbenchApi.reject(id)
      success(`操作成功`)
      setDetailOpen(false)
      load()
    } catch (e) { error((e as Error).message) }
  }

  const handleDelete = async () => {
    if (!deleteTarget) return
    try {
      await vouchersApi.delete(deleteTarget)
      success('凭证已删除')
      setDeleteTarget(null); load()
    } catch (e) { error((e as Error).message) }
  }

  const openTrash = async () => {
    try {
      setTrashVouchers(await vouchersApi.trash())
      setTrashOpen(true)
    } catch (e) { error((e as Error).message) }
  }

  const restore = async (id: number) => {
    try {
      await vouchersApi.restore(id)
      success('凭证已恢复')
      setTrashVouchers(prev => prev.filter(v => v.voucher_id !== id))
      load()
    } catch (e) { error((e as Error).message) }
  }

  const handleReorg = async () => {
    try {
      const r = await vouchersApi.reorganize(reorgYear, reorgMonth)
      success(`断号整理完成，共整理 ${r.reorganized_count} 条`)
      setReorgOpen(false); load()
    } catch (e) { error((e as Error).message) }
  }

  const filters: [StatusFilter, string][] = [['ALL', '全部'], ['DRAFT', '草稿'], ['PENDING_REVIEW', '待审核'], ['POSTED', '已过账']]

  if (loading) return <PageLoader />

  return (
    <div className="p-6 max-w-5xl">
      <div className="flex items-center justify-between mb-5">
        <h1 className="text-xl font-bold text-slate-800">凭证管理</h1>
        <div className="flex gap-2">
          <button onClick={openTrash} className="px-3 py-1.5 text-xs border border-slate-300 rounded-lg hover:bg-slate-50">🗑 回收站</button>
          <button onClick={() => setReorgOpen(true)} className="px-3 py-1.5 text-xs border border-slate-300 rounded-lg hover:bg-slate-50">🔢 断号整理</button>
        </div>
      </div>

      {/* 状态筛选 */}
      <div className="flex gap-1 mb-4 border-b border-slate-200">
        {filters.map(([key, label]) => (
          <button key={key} onClick={() => setFilter(key)}
            className={`px-4 py-2 text-sm border-b-2 transition-colors ${filter === key ? 'border-primary-600 text-primary-700 font-medium' : 'border-transparent text-slate-500 hover:text-slate-700'}`}>
            {label}
          </button>
        ))}
      </div>

      {/* 列表 */}
      <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-slate-50">
            <tr className="text-xs text-slate-500">
              <th className="px-4 py-3 text-left">凭证号</th>
              <th className="px-4 py-3 text-left">日期</th>
              <th className="px-4 py-3 text-left">摘要</th>
              <th className="px-4 py-3 text-right">借方金额</th>
              <th className="px-4 py-3 text-center">状态</th>
              <th className="px-4 py-3"></th>
            </tr>
          </thead>
          <tbody>
            {vouchers.length === 0 && (
              <tr><td colSpan={6} className="px-4 py-10 text-center text-slate-400">暂无凭证</td></tr>
            )}
            {vouchers.map(v => (
              <tr key={v.voucher_id} className="border-t border-slate-100 hover:bg-slate-50/50 cursor-pointer" onClick={() => openDetail(v)}>
                <td className="px-4 py-3 font-medium">{v.voucher_word}{v.voucher_number ?? '-'}</td>
                <td className="px-4 py-3 text-slate-500">{v.voucher_date}</td>
                <td className="px-4 py-3 truncate max-w-xs">{v.description}</td>
                <td className="px-4 py-3 text-right font-mono">¥{fmt(v.total_debit)}</td>
                <td className="px-4 py-3 text-center"><ReviewStatusBadge status={v.review_status} /></td>
                <td className="px-4 py-3 text-right" onClick={e => e.stopPropagation()}>
                  {v.review_status === 'DRAFT' && (
                    <button onClick={() => setDeleteTarget(v.voucher_id)}
                      className="text-xs text-red-500 hover:underline">删除</button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* 详情 Modal */}
      <Modal open={detailOpen} onClose={() => setDetailOpen(false)} title={`凭证详情 #${selected?.voucher_id}`} width="max-w-2xl"
        footer={selected && (
          <>
            {selected.review_status === 'DRAFT' && (
              <button onClick={() => handleAction('submit', selected.voucher_id)}
                className="px-3 py-1.5 text-sm bg-primary-600 text-white rounded-lg hover:bg-primary-700">提交审核</button>
            )}
            {selected.review_status === 'PENDING_REVIEW' && (
              <>
                <button onClick={() => handleAction('reject', selected.voucher_id)}
                  className="px-3 py-1.5 text-sm border border-red-400 text-red-600 rounded-lg hover:bg-red-50">驳回</button>
                <button onClick={() => handleAction('post', selected.voucher_id)}
                  className="px-3 py-1.5 text-sm bg-green-600 text-white rounded-lg hover:bg-green-700">过账</button>
              </>
            )}
          </>
        )}>
        {selected && (
          <div>
            <div className="grid grid-cols-2 gap-3 mb-4 text-sm text-slate-600">
              <div>日期：{selected.voucher_date}</div>
              <div>凭证字号：{selected.voucher_word}{selected.voucher_number ?? '-'}</div>
              <div className="col-span-2">摘要：{selected.description}</div>
            </div>
            <table className="w-full text-xs">
              <thead className="bg-slate-50"><tr className="text-slate-500">
                <th className="px-3 py-2 text-left">科目</th>
                <th className="px-3 py-2 text-center">方向</th>
                <th className="px-3 py-2 text-right">金额</th>
              </tr></thead>
              <tbody>
                {selected.lines.map((l, i) => (
                  <tr key={i} className="border-t border-slate-100">
                    <td className="px-3 py-2">{l.subject_code} {l.subject_name}</td>
                    <td className="px-3 py-2 text-center">{l.direction === 'DEBIT' ? '借' : '贷'}</td>
                    <td className="px-3 py-2 text-right font-mono">¥{fmt(l.amount)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Modal>

      {/* 回收站 Modal */}
      <Modal open={trashOpen} onClose={() => setTrashOpen(false)} title="回收站" width="max-w-2xl">
        {trashVouchers.length === 0 ? (
          <p className="text-center text-slate-400 py-8">回收站为空</p>
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-slate-50"><tr className="text-xs text-slate-500">
              <th className="px-4 py-2 text-left">凭证号</th>
              <th className="px-4 py-2 text-left">摘要</th>
              <th className="px-4 py-2 text-right">金额</th>
              <th className="px-4 py-2"></th>
            </tr></thead>
            <tbody>
              {trashVouchers.map(v => (
                <tr key={v.voucher_id} className="border-t border-slate-100">
                  <td className="px-4 py-2">{v.voucher_word}{v.voucher_number ?? '-'}</td>
                  <td className="px-4 py-2 truncate max-w-xs">{v.description}</td>
                  <td className="px-4 py-2 text-right font-mono">¥{fmt(v.total_debit)}</td>
                  <td className="px-4 py-2 text-right">
                    <button onClick={() => restore(v.voucher_id)} className="text-xs text-primary-600 hover:underline">恢复</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Modal>

      {/* 断号整理 Modal */}
      <Modal open={reorgOpen} onClose={() => setReorgOpen(false)} title="断号整理"
        footer={
          <>
            <button onClick={() => setReorgOpen(false)} className="px-3 py-1.5 text-sm border border-slate-300 rounded-lg">取消</button>
            <button onClick={handleReorg} className="px-3 py-1.5 text-sm bg-primary-600 text-white rounded-lg hover:bg-primary-700">确认整理</button>
          </>
        }>
        <div className="flex gap-3">
          <div>
            <label className="text-xs text-slate-500 block mb-1">年份</label>
            <input type="number" value={reorgYear} onChange={e => setReorgYear(+e.target.value)}
              className="border border-slate-200 rounded-lg px-3 py-2 text-sm w-24 focus:outline-none focus:ring-2 focus:ring-primary-500" />
          </div>
          <div>
            <label className="text-xs text-slate-500 block mb-1">月份</label>
            <input type="number" min={1} max={12} value={reorgMonth} onChange={e => setReorgMonth(+e.target.value)}
              className="border border-slate-200 rounded-lg px-3 py-2 text-sm w-20 focus:outline-none focus:ring-2 focus:ring-primary-500" />
          </div>
        </div>
      </Modal>

      <ConfirmDialog open={deleteTarget !== null} title="删除凭证" message="确认删除此凭证？" confirmLabel="删除" danger
        onConfirm={handleDelete} onCancel={() => setDeleteTarget(null)} />
    </div>
  )
}
