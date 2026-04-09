import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { reportsApi } from '@/api/reports'
import { subjectsApi } from '@/api/subjects'
import { VoucherViewerModal } from '@/components/common/VoucherViewerModal'
import type { DetailedLedgerRow, SubjectNode } from '@/types'

// ── Helpers ───────────────────────────────────────────────────────────────────

function defaultDateFrom(): string {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-01`
}
function defaultDateTo(): string {
  return new Date().toISOString().slice(0, 10)
}

function flattenSubjects(nodes: SubjectNode[]): SubjectNode[] {
  const result: SubjectNode[] = []
  const traverse = (node: SubjectNode) => {
    result.push(node)
    node.children?.forEach(traverse)
  }
  nodes.forEach(traverse)
  return result
}

function fmt(n: number): string {
  if (n === 0) return ''
  return n.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}
function fmtTotal(n: number): string {
  return n.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

function rowBg(row_type: DetailedLedgerRow['row_type']): string {
  if (row_type === 'opening')                             return 'bg-blue-50 font-semibold'
  if (row_type === 'period_total' || row_type === 'ytd_total') return 'bg-gray-100 font-semibold text-gray-600'
  return 'hover:bg-blue-50/40 transition-colors'
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function DetailedLedgerPage() {
  const [searchParams, setSearchParams] = useSearchParams()

  // URL params (applied filter)
  const urlSubject  = searchParams.get('subject_code') ?? ''
  const urlDateFrom = searchParams.get('date_from')    ?? defaultDateFrom()
  const urlDateTo   = searchParams.get('date_to')      ?? defaultDateTo()

  // Draft toolbar state (before hitting Query)
  const [draftFrom, setDraftFrom] = useState(urlDateFrom)
  const [draftTo,   setDraftTo]   = useState(urlDateTo)
  const [draftKw,   setDraftKw]   = useState('')

  // Applied keyword (updated on query)
  const [keyword, setKeyword] = useState('')

  // Data state
  const [rows,     setRows]     = useState<DetailedLedgerRow[]>([])
  const [loading,  setLoading]  = useState(false)
  const [error,    setError]    = useState<string | null>(null)

  // Subjects for quick switch
  const [subjects,  setSubjects]  = useState<SubjectNode[]>([])
  const [subSearch, setSubSearch] = useState('')

  // Voucher viewer modal
  const [viewerId, setViewerId] = useState<number | null>(null)

  // Sync drafts when URL changes (e.g. when subject switched from sidebar)
  useEffect(() => {
    setDraftFrom(urlDateFrom)
    setDraftTo(urlDateTo)
  }, [urlDateFrom, urlDateTo])

  // Load flat subjects list for quick switch
  useEffect(() => {
    subjectsApi.tree()
      .then(tree => setSubjects(flattenSubjects(tree).filter(s => s.is_enabled)))
      .catch(() => {})
  }, [])

  // Fetch ledger when URL params or keyword changes
  useEffect(() => {
    if (!urlSubject) { setRows([]); return }
    setLoading(true)
    setError(null)
    reportsApi.detailedLedger({
      subject_code: urlSubject,
      date_from:    urlDateFrom,
      date_to:      urlDateTo,
      keyword:      keyword || undefined,
    })
      .then(resp  => setRows(resp.rows))
      .catch(e    => setError(typeof e?.detail === 'string' ? e.detail : '查询失败，请检查科目编码'))
      .finally(() => setLoading(false))
  }, [urlSubject, urlDateFrom, urlDateTo, keyword])

  // Query button: push drafts to URL + apply keyword
  const handleQuery = () => {
    const p: Record<string, string> = {
      date_from: draftFrom,
      date_to:   draftTo,
    }
    if (urlSubject) p.subject_code = urlSubject
    setKeyword(draftKw)
    setSearchParams(p)
  }

  // Switch subject from quick-switch panel
  const switchSubject = (code: string) => {
    setKeyword('')
    setDraftKw('')
    setSearchParams({ subject_code: code, date_from: urlDateFrom, date_to: urlDateTo })
  }

  // Filtered subjects for right panel
  const filteredSubjects = subjects.filter(s =>
    !subSearch ||
    s.subject_code.includes(subSearch) ||
    s.subject_name.includes(subSearch)
  )

  const subjectName = rows.length > 0 ? rows[0].subject_name : ''

  return (
    <div className="flex h-full gap-3 p-4 overflow-hidden">

      {/* ── Main content ──────────────────────────────────────────── */}
      <div className="flex-1 min-w-0 flex flex-col gap-3 overflow-hidden">

        {/* Toolbar */}
        <div className="bg-white rounded-xl border border-gray-200 px-4 py-3 flex flex-wrap items-end gap-3 shrink-0 print:hidden">
          <div className="flex flex-col gap-1">
            <label className="text-xs text-gray-500">起始日期</label>
            <input
              type="date"
              value={draftFrom}
              onChange={e => setDraftFrom(e.target.value)}
              className="border border-gray-200 rounded px-2 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-blue-400"
            />
          </div>
          <div className="flex flex-col gap-1">
            <label className="text-xs text-gray-500">截止日期</label>
            <input
              type="date"
              value={draftTo}
              onChange={e => setDraftTo(e.target.value)}
              className="border border-gray-200 rounded px-2 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-blue-400"
            />
          </div>
          <div className="flex flex-col gap-1">
            <label className="text-xs text-gray-500">摘要关键字</label>
            <input
              type="text"
              placeholder="模糊搜索…"
              value={draftKw}
              onChange={e => setDraftKw(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter') handleQuery() }}
              className="border border-gray-200 rounded px-2 py-1.5 text-sm w-36 focus:outline-none focus:ring-1 focus:ring-blue-400"
            />
          </div>
          <button
            onClick={handleQuery}
            className="px-4 py-1.5 rounded bg-blue-600 text-white text-sm font-medium hover:bg-blue-700 transition-colors"
          >
            查询
          </button>
          <button
            onClick={() => window.print()}
            className="px-4 py-1.5 rounded border border-gray-300 text-sm text-gray-600 hover:bg-gray-50 transition-colors"
          >
            打印
          </button>
        </div>

        {/* Subject title */}
        <div className="px-1 shrink-0">
          {urlSubject ? (
            <span className="text-base font-semibold text-gray-700">
              明细账 — <span className="font-mono text-gray-500 text-sm">{urlSubject}</span>
              {subjectName && ` ${subjectName}`}
            </span>
          ) : (
            <span className="text-sm text-gray-400">请从右侧选择科目，或通过科目余额表点击科目名称进入。</span>
          )}
        </div>

        {/* Error banner */}
        {error && (
          <div className="bg-red-50 border border-red-300 text-red-700 text-sm rounded-lg px-4 py-3 shrink-0">
            {error}
          </div>
        )}

        {/* Table */}
        {urlSubject && (
          <div className="bg-white rounded-xl border border-gray-200 overflow-auto flex-1">
            <table className="w-full text-sm border-collapse">
              <thead>
                <tr className="bg-gray-50 sticky top-0 z-10">
                  {['日期','凭证字号','科目','摘要','借方','贷方','方向','余额'].map(h => (
                    <th
                      key={h}
                      className="border border-gray-100 px-3 py-2 font-medium text-gray-600 whitespace-nowrap text-left"
                    >
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {loading ? (
                  <tr>
                    <td colSpan={8} className="py-12 text-center text-gray-400 text-sm">
                      计算中…
                    </td>
                  </tr>
                ) : rows.length === 0 ? (
                  <tr>
                    <td colSpan={8} className="py-12 text-center text-gray-400 text-sm">
                      该期间无发生额
                    </td>
                  </tr>
                ) : (
                  rows.map((row, idx) => (
                    <LedgerRow key={idx} row={row} onViewVoucher={setViewerId} />
                  ))
                )}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* ── Right quick-switch panel ───────────────────────────────── */}
      <div className="w-48 shrink-0 bg-white rounded-xl border border-gray-200 flex flex-col overflow-hidden print:hidden">
        <div className="px-3 py-2 border-b border-gray-100 text-xs font-semibold text-gray-500 tracking-wide shrink-0">
          快速切换
        </div>
        <div className="px-2 py-1.5 border-b border-gray-100 shrink-0">
          <input
            type="text"
            placeholder="搜索科目…"
            value={subSearch}
            onChange={e => setSubSearch(e.target.value)}
            className="w-full border border-gray-200 rounded px-2 py-1 text-xs focus:outline-none focus:ring-1 focus:ring-blue-400"
          />
        </div>
        <div className="flex-1 overflow-y-auto">
          {filteredSubjects.map(s => (
            <button
              key={s.subject_code}
              onClick={() => switchSubject(s.subject_code)}
              className={`w-full text-left px-2 py-1.5 text-xs flex items-baseline gap-1 transition-colors ${
                s.subject_code === urlSubject
                  ? 'bg-blue-100 text-blue-700 font-medium'
                  : 'text-gray-600 hover:bg-gray-50'
              }`}
            >
              <span className="font-mono text-gray-400 shrink-0 text-[10px]">{s.subject_code}</span>
              <span className="truncate">{s.subject_name}</span>
            </button>
          ))}
          {filteredSubjects.length === 0 && (
            <div className="py-4 text-center text-xs text-gray-400">无匹配科目</div>
          )}
        </div>
      </div>

      {/* Voucher viewer modal */}
      <VoucherViewerModal voucherId={viewerId} onClose={() => setViewerId(null)} />
    </div>
  )
}

// ── Single table row ──────────────────────────────────────────────────────────

function LedgerRow({
  row,
  onViewVoucher,
}: {
  row: DetailedLedgerRow
  onViewVoucher: (id: number) => void
}) {
  const isSpecial = row.row_type !== 'transaction'
  const bg        = rowBg(row.row_type)

  return (
    <tr className={bg}>
      {/* 日期 */}
      <td className="border border-gray-100 px-3 py-1.5 whitespace-nowrap text-gray-600">
        {row.date ?? ''}
      </td>

      {/* 凭证字号 */}
      <td className="border border-gray-100 px-3 py-1.5 whitespace-nowrap">
        {!isSpecial && row.voucher_id != null ? (
          <button
            className="text-blue-600 hover:underline font-mono text-xs"
            onClick={() => onViewVoucher(row.voucher_id!)}
          >
            {row.voucher_word}{row.voucher_number}
          </button>
        ) : null}
      </td>

      {/* 科目 */}
      <td className="border border-gray-100 px-3 py-1.5 text-gray-500 font-mono text-xs whitespace-nowrap">
        {isSpecial ? '' : row.subject_code}
      </td>

      {/* 摘要 */}
      <td className="border border-gray-100 px-3 py-1.5 text-gray-700 max-w-xs truncate">
        {row.memo ?? ''}
      </td>

      {/* 借方 */}
      <td className="border border-gray-100 px-3 py-1.5 text-right tabular-nums text-gray-800">
        {isSpecial ? fmtTotal(row.debit) : fmt(row.debit)}
      </td>

      {/* 贷方 */}
      <td className="border border-gray-100 px-3 py-1.5 text-right tabular-nums text-gray-800">
        {isSpecial ? fmtTotal(row.credit) : fmt(row.credit)}
      </td>

      {/* 方向 */}
      <td className="border border-gray-100 px-3 py-1.5 text-center">
        {row.direction != null && (
          <span className={`text-xs font-medium ${
            row.direction === '借' ? 'text-blue-600'   :
            row.direction === '贷' ? 'text-orange-600' :
            'text-gray-400'
          }`}>
            {row.direction}
          </span>
        )}
      </td>

      {/* 余额 */}
      <td className="border border-gray-100 px-3 py-1.5 text-right tabular-nums text-gray-800">
        {row.balance != null ? fmtTotal(row.balance) : ''}
      </td>
    </tr>
  )
}
