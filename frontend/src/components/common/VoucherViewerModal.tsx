import { useEffect, useState } from 'react'
import { Modal } from './Modal'
import { vouchersApi } from '@/api/vouchers'
import type { VoucherOut } from '@/types'

interface Props {
  voucherId: number | null
  onClose:   () => void
}

const DEBIT_LABEL:  Record<string, string> = { DEBIT: '借', CREDIT: '贷' }

function fmt(n: number): string {
  return n.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

export function VoucherViewerModal({ voucherId, onClose }: Props) {
  const [voucher, setVoucher] = useState<VoucherOut | null>(null)
  const [loading, setLoading] = useState(false)
  const [error,   setError]   = useState<string | null>(null)

  useEffect(() => {
    if (voucherId == null) { setVoucher(null); return }
    setLoading(true)
    setError(null)
    vouchersApi.get(voucherId)
      .then(v  => setVoucher(v))
      .catch(() => setError('凭证加载失败'))
      .finally(() => setLoading(false))
  }, [voucherId])

  const title = voucher
    ? `凭证详情 — ${voucher.voucher_word ?? '记'}${voucher.voucher_number ?? ''} （${voucher.voucher_date}）`
    : '凭证详情'

  return (
    <Modal open={voucherId != null} onClose={onClose} title={title} width="max-w-4xl">
      {loading && (
        <div className="py-12 text-center text-gray-400 text-sm">加载中…</div>
      )}

      {error && (
        <div className="py-6 text-center text-red-500 text-sm">{error}</div>
      )}

      {voucher && !loading && (
        <div className="space-y-4">
          {/* 凭证头信息 */}
          <div className="grid grid-cols-3 gap-4 text-sm text-gray-600 bg-gray-50 rounded-lg p-3">
            <div><span className="text-gray-400">日期：</span>{voucher.voucher_date}</div>
            <div>
              <span className="text-gray-400">字号：</span>
              {voucher.voucher_word ?? '记'}-{voucher.voucher_number ?? '—'}
            </div>
            <div>
              <span className="text-gray-400">状态：</span>
              <span className={
                voucher.review_status === 'POSTED'
                  ? 'text-green-600 font-medium'
                  : 'text-yellow-600 font-medium'
              }>
                {{ DRAFT: '草稿', PENDING_REVIEW: '待审核', POSTED: '已过账', REJECTED: '已拒绝' }[voucher.review_status] ?? voucher.review_status}
              </span>
            </div>
            {voucher.memo && (
              <div className="col-span-3">
                <span className="text-gray-400">摘要：</span>{voucher.memo}
              </div>
            )}
          </div>

          {/* 凭证行明细 */}
          <table className="w-full text-sm border-collapse">
            <thead>
              <tr className="bg-gray-100">
                <th className="border border-gray-200 px-3 py-2 text-left font-medium text-gray-600">科目代码</th>
                <th className="border border-gray-200 px-3 py-2 text-left font-medium text-gray-600">摘要</th>
                <th className="border border-gray-200 px-3 py-2 text-center font-medium text-gray-600">方向</th>
                <th className="border border-gray-200 px-3 py-2 text-right font-medium text-gray-600">借方</th>
                <th className="border border-gray-200 px-3 py-2 text-right font-medium text-gray-600">贷方</th>
              </tr>
            </thead>
            <tbody>
              {voucher.lines.map((line, idx) => (
                <tr key={idx} className="hover:bg-gray-50">
                  <td className="border border-gray-200 px-3 py-1.5 font-mono text-xs text-gray-600">
                    {line.subject_code}
                    {line.subject_name && (
                      <span className="ml-1 text-gray-500">{line.subject_name}</span>
                    )}
                  </td>
                  <td className="border border-gray-200 px-3 py-1.5 text-gray-700">
                    {line.memo ?? ''}
                  </td>
                  <td className="border border-gray-200 px-3 py-1.5 text-center">
                    <span className={`text-xs font-medium ${line.direction === 'DEBIT' ? 'text-blue-600' : 'text-orange-600'}`}>
                      {DEBIT_LABEL[line.direction]}
                    </span>
                  </td>
                  <td className="border border-gray-200 px-3 py-1.5 text-right tabular-nums text-gray-800">
                    {line.direction === 'DEBIT' ? fmt(line.amount) : ''}
                  </td>
                  <td className="border border-gray-200 px-3 py-1.5 text-right tabular-nums text-gray-800">
                    {line.direction === 'CREDIT' ? fmt(line.amount) : ''}
                  </td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr className="bg-gray-50 font-semibold">
                <td colSpan={3} className="border border-gray-200 px-3 py-1.5 text-gray-600 text-right">合计</td>
                <td className="border border-gray-200 px-3 py-1.5 text-right tabular-nums text-gray-800">
                  {fmt(voucher.lines.filter(l => l.direction === 'DEBIT').reduce((s, l) => s + l.amount, 0))}
                </td>
                <td className="border border-gray-200 px-3 py-1.5 text-right tabular-nums text-gray-800">
                  {fmt(voucher.lines.filter(l => l.direction === 'CREDIT').reduce((s, l) => s + l.amount, 0))}
                </td>
              </tr>
            </tfoot>
          </table>
        </div>
      )}
    </Modal>
  )
}
