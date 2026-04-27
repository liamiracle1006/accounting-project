import { useState, useEffect } from 'react'
import { useVoucherStore } from '@/store/useVoucherStore'
import { useToast } from '@/hooks/useToast'
import { vouchersApi } from '@/api/vouchers'
import { SettleDialog } from './SettleDialog'
import type { VoucherLine } from '@/types'

const fmt = (n: number) => n.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

interface Props {
  description: string
  voucherDate: string
  voucherWord: string
  onSuccess: (voucherId: number) => void
}

export function VoucherEditor({ description, voucherDate, voucherWord, onSuccess }: Props) {
  const { draft, selectedHabitRuleId, aiOriginalLineCodes, reset } = useVoucherStore()
  const { success, error } = useToast()
  const [memo, setMemo] = useState('')
  const [lines, setLines] = useState<VoucherLine[]>([])
  const [loading, setLoading] = useState(false)
  const [settleOpen, setSettleOpen] = useState(false)

  useEffect(() => {
    if (draft) {
      setMemo(draft.memo ?? '')
      setLines(draft.lines.map(l => ({ ...l })))
    }
  }, [draft])

  if (!draft) return null

  const totalDebit  = lines.filter(l => l.direction === 'DEBIT').reduce((s, l) => s + (l.amount || 0), 0)
  const totalCredit = lines.filter(l => l.direction === 'CREDIT').reduce((s, l) => s + (l.amount || 0), 0)
  const balanced    = Math.abs(totalDebit - totalCredit) < 0.005

  const updateLine = (idx: number, key: keyof VoucherLine, value: unknown) => {
    setLines(prev => prev.map((l, i) => i === idx ? { ...l, [key]: value } : l))
  }
  const addLine = () => setLines(prev => [...prev, { subject_code: '', direction: 'DEBIT', amount: 0, memo: null }])
  const removeLine = (idx: number) => {
    if (lines.length <= 2) { error('至少保留 2 行'); return }
    setLines(prev => prev.filter((_, i) => i !== idx))
  }

  const isAiSubjectModified = () => {
    if (!aiOriginalLineCodes.length) return false
    const current = lines.map(l => l.subject_code)
    return JSON.stringify(current) !== JSON.stringify(aiOriginalLineCodes)
  }

  const doConfirm = async (keepRule: boolean) => {
    const validLines = lines.filter(l => l.subject_code && l.amount > 0)
    if (validLines.length < 2) { error('请填写完整的科目编码和金额'); return }
    setLoading(true)
    try {
      const v = await vouchersApi.confirm({
        description, voucher_date: voucherDate, voucher_word: voucherWord,
        memo,
        lines: validLines,
        habit_rule_id: keepRule ? selectedHabitRuleId : null,
      })
      success(`✅ 凭证 #${v.voucher_id} 已入账`)
      reset()
      onSuccess(v.voucher_id)
    } catch (e) {
      error((e as Error).message)
    } finally {
      setLoading(false)
    }
  }

  const handleConfirmClick = () => {
    if (!balanced) { error('借贷不平衡，请检查金额'); return }
    if (isAiSubjectModified()) {
      setSettleOpen(true)
    } else {
      doConfirm(true)
    }
  }

  return (
    <div className="bg-white border border-slate-200 rounded-xl p-4">
      {draft.circuit_breaker_triggered && (
        <div className="mb-3 px-3 py-2 bg-amber-50 border border-amber-200 rounded-lg text-sm text-amber-700">
          ⚠️ 断路器已触发：{draft.pending_review_reason ?? '借贷不平，请人工复核'}
        </div>
      )}

      <div className="mb-3">
        <label className="text-xs font-medium text-slate-500 block mb-1">摘要</label>
        <input
          value={memo}
          onChange={e => setMemo(e.target.value)}
          className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500"
        />
      </div>

      <table className="w-full text-sm mb-3">
        <thead>
          <tr className="bg-slate-50 text-slate-500 text-xs">
            <th className="px-2 py-2 text-left">科目编码</th>
            <th className="px-2 py-2 text-center">方向</th>
            <th className="px-2 py-2 text-right">金额</th>
            <th className="px-2 py-2 text-left">备注</th>
            <th className="px-2 py-2 w-6"></th>
          </tr>
        </thead>
        <tbody>
          {lines.map((line, idx) => (
            <tr key={idx} className="border-t border-slate-100">
              <td className="px-2 py-1">
                <input
                  value={line.subject_code}
                  onChange={e => updateLine(idx, 'subject_code', e.target.value)}
                  className="w-24 border border-slate-200 rounded px-2 py-1 text-xs focus:outline-none focus:ring-1 focus:ring-primary-500"
                  placeholder="科目编码"
                />
              </td>
              <td className="px-2 py-1 text-center">
                <select
                  value={line.direction}
                  onChange={e => updateLine(idx, 'direction', e.target.value)}
                  className="border border-slate-200 rounded px-1 py-1 text-xs"
                >
                  <option value="DEBIT">借</option>
                  <option value="CREDIT">贷</option>
                </select>
              </td>
              <td className="px-2 py-1">
                <input
                  type="number" min="0.01" step="0.01"
                  value={line.amount || ''}
                  onChange={e => updateLine(idx, 'amount', parseFloat(e.target.value) || 0)}
                  className="w-28 border border-slate-200 rounded px-2 py-1 text-xs text-right focus:outline-none focus:ring-1 focus:ring-primary-500"
                />
              </td>
              <td className="px-2 py-1">
                <input
                  value={line.memo ?? ''}
                  onChange={e => updateLine(idx, 'memo', e.target.value || null)}
                  className="w-24 border border-slate-200 rounded px-2 py-1 text-xs"
                  placeholder="备注"
                />
              </td>
              <td className="px-2 py-1 text-center">
                <button onClick={() => removeLine(idx)} className="text-red-400 hover:text-red-600 text-base leading-none">×</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <div className="flex items-center justify-between mb-3">
        <button onClick={addLine} className="text-xs text-primary-600 hover:underline">+ 添加行</button>
        <div className="flex gap-4 text-xs">
          <span>借方: ¥{fmt(totalDebit)}</span>
          <span>贷方: ¥{fmt(totalCredit)}</span>
          <span className={balanced ? 'text-green-600 font-medium' : 'text-red-600 font-medium'}>
            {balanced ? '✅ 借贷平衡' : '❌ 借贷不平'}
          </span>
        </div>
      </div>

      <button
        onClick={handleConfirmClick}
        disabled={loading || !balanced}
        className="w-full py-2 bg-primary-600 hover:bg-primary-700 disabled:bg-slate-300 text-white text-sm rounded-lg font-medium transition-colors"
      >
        {loading ? '入账中…' : '确认入账'}
      </button>

      <SettleDialog
        open={settleOpen}
        onKeepRule={() => { setSettleOpen(false); doConfirm(true) }}
        onIgnore={() => { setSettleOpen(false); doConfirm(false) }}
      />
    </div>
  )
}
