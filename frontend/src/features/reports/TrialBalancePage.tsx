/**
 * Sprint 4.1 — 科目余额表 (Trial Balance)
 *
 * 功能：
 *  - 顶部操作栏：期间选择 + 高级筛选气泡（科目级别 / 隐藏零余额 / 科目范围）
 *  - 多级分组表头：科目编码 | 科目名称 | 期初余额(借/贷) | 本期发生(借/贷) | 期末余额(借/贷)
 *  - 树状缩进：level 每增一级缩进 20px，1 级科目加粗
 *  - "见红"逻辑：余额方向与科目固有方向相反时文本红色
 *  - 底部合计行 + 试算平衡警告
 *  - 导出 Excel（真实 .xlsx，多级表头合并单元格）
 *  - 打印（window.print() + @media print CSS）
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import * as XLSX from 'xlsx'
import { reportsApi } from '@/api/reports'
import { useReportStore } from '@/store/useReportStore'
import type { TrialBalanceItem } from '@/types'

// ── 金额格式化 ─────────────────────────────────────────────────────────────
function fmt(n: number): string {
  if (n === 0) return ''
  return n.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

function fmtTotal(n: number): string {
  return n.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

// ── "见红"判断 ────────────────────────────────────────────────────────────
// 科目固有方向 vs 实际余额所在方向不一致时返回 true
function isReversed(item: TrialBalanceItem, which: 'opening' | 'closing'): boolean {
  const debit  = which === 'opening' ? item.opening_debit  : item.closing_debit
  const credit = which === 'opening' ? item.opening_credit : item.closing_credit
  if (debit === 0 && credit === 0) return false
  if (item.direction === '借' && credit > 0) return true
  if (item.direction === '贷' && debit  > 0) return true
  return false
}

// ── 数字输入组件 ───────────────────────────────────────────────────────────
function NumberInput({
  label, value, onChange,
}: { label: string; value: string; onChange: (v: string) => void }) {
  return (
    <div className="flex flex-col gap-1">
      <label className="text-xs text-gray-500">{label}</label>
      <input
        type="number" min={1} max={10} value={value}
        onChange={e => onChange(e.target.value)}
        className="w-16 border border-gray-300 rounded px-2 py-1 text-sm"
      />
    </div>
  )
}

// ═══════════════════════════════════════════════════════════════════════════
export default function TrialBalancePage() {
  const {
    tbParams, tbItems, tbTotals, tbBalanced,
    tbOpeningBalanced, tbCurrentBalanced, tbClosingBalanced,
    tbLoading, tbError,
    setTbParams, setTbData, setTbLoading, setTbError,
  } = useReportStore()

  // 高级筛选气泡开关
  const [filterOpen, setFilterOpen] = useState(false)
  const filterRef = useRef<HTMLDivElement>(null)

  // 高级筛选本地草稿（关闭或查询时才提交）
  const [draftMaxLevel,   setDraftMaxLevel]   = useState(String(tbParams.max_level   ?? ''))
  const [draftStartCode,  setDraftStartCode]  = useState(tbParams.start_subject_code ?? '')
  const [draftEndCode,    setDraftEndCode]    = useState(tbParams.end_subject_code   ?? '')

  // 点击气泡外部时关闭
  useEffect(() => {
    function onClickOutside(e: MouseEvent) {
      if (filterRef.current && !filterRef.current.contains(e.target as Node)) {
        setFilterOpen(false)
      }
    }
    document.addEventListener('mousedown', onClickOutside)
    return () => document.removeEventListener('mousedown', onClickOutside)
  }, [])

  // ── 数据加载 ──────────────────────────────────────────────────────────
  const load = useCallback(async (overrides?: Partial<typeof tbParams>) => {
    const params = { ...tbParams, ...overrides }
    setTbLoading(true)
    try {
      const res = await reportsApi.trialBalance(params)
      setTbData(
        res.items, res.totals, res.balanced,
        res.opening_balanced, res.current_balanced, res.closing_balanced,
      )
      if (!res.balanced) {
        console.error('[TrialBalance] 试算不平衡！', res.totals)
      }
    } catch (e: unknown) {
      setTbError(e instanceof Error ? e.message : '加载失败')
    }
  }, [tbParams, setTbLoading, setTbData, setTbError])

  // 首次加载
  useEffect(() => { load() }, []) // eslint-disable-line react-hooks/exhaustive-deps

  // ── 提交筛选 ──────────────────────────────────────────────────────────
  function applyFilter() {
    const updates: Partial<typeof tbParams> = {
      max_level:          draftMaxLevel  ? parseInt(draftMaxLevel)  : undefined,
      start_subject_code: draftStartCode || undefined,
      end_subject_code:   draftEndCode   || undefined,
    }
    setTbParams(updates)
    setFilterOpen(false)
    load(updates)
  }

  // ── 导出 Excel ────────────────────────────────────────────────────────
  function exportExcel() {
    const wb  = XLSX.utils.book_new()

    // 行数据：多级表头（2行）+ 数据行 + 合计行
    const header1 = ['科目编码', '科目名称', '期初余额', '', '本期发生额', '', '期末余额', '']
    const header2 = ['', '', '借方', '贷方', '借方', '贷方', '借方', '贷方']
    const dataRows = tbItems.map(item => [
      item.code,
      item.name,
      item.opening_debit  || '',
      item.opening_credit || '',
      item.current_debit  || '',
      item.current_credit || '',
      item.closing_debit  || '',
      item.closing_credit || '',
    ])
    const totalRow = tbTotals ? [
      '合计', '',
      tbTotals.opening_debit,  tbTotals.opening_credit,
      tbTotals.current_debit,  tbTotals.current_credit,
      tbTotals.closing_debit,  tbTotals.closing_credit,
    ] : []

    const ws = XLSX.utils.aoa_to_sheet([header1, header2, ...dataRows, totalRow])

    // 合并单元格：多级表头
    ws['!merges'] = [
      { s: { r: 0, c: 0 }, e: { r: 1, c: 0 } },  // 科目编码
      { s: { r: 0, c: 1 }, e: { r: 1, c: 1 } },  // 科目名称
      { s: { r: 0, c: 2 }, e: { r: 0, c: 3 } },  // 期初余额
      { s: { r: 0, c: 4 }, e: { r: 0, c: 5 } },  // 本期发生额
      { s: { r: 0, c: 6 }, e: { r: 0, c: 7 } },  // 期末余额
    ]

    // 列宽
    ws['!cols'] = [
      { wch: 12 }, { wch: 24 },
      { wch: 14 }, { wch: 14 },
      { wch: 14 }, { wch: 14 },
      { wch: 14 }, { wch: 14 },
    ]

    // 金额单元格数字格式
    const numFmt = '#,##0.00'
    const totalRows = 2 + tbItems.length
    for (let r = 2; r <= totalRows; r++) {
      for (const c of [2, 3, 4, 5, 6, 7]) {
        const addr = XLSX.utils.encode_cell({ r, c })
        if (ws[addr] && typeof ws[addr].v === 'number') {
          ws[addr].z = numFmt
        }
      }
    }

    XLSX.utils.book_append_sheet(wb, ws, '科目余额表')
    XLSX.writeFile(wb, `科目余额表_${tbParams.date_from}_${tbParams.date_to}.xlsx`)
  }

  // ── 打印 ───────────────────────────────────────────────────────────────
  function handlePrint() {
    window.print()
  }

  // ═══════════════════════════════════════════════════════════════════
  // 渲染
  // ═══════════════════════════════════════════════════════════════════
  return (
    <div className="p-4 print:p-0">

      {/* ── 顶部操作栏 ─────────────────────────────────────────────── */}
      <div className="flex items-center justify-between mb-4 print:hidden">
        <div className="flex items-center gap-3 flex-wrap">
          <h1 className="text-lg font-bold text-gray-800">科目余额表</h1>

          {/* 期间选择 */}
          <div className="flex items-center gap-1 text-sm">
            <label className="text-gray-500">从</label>
            <input
              type="date"
              value={tbParams.date_from ?? ''}
              onChange={e => setTbParams({ date_from: e.target.value })}
              className="border border-gray-300 rounded px-2 py-1 text-sm"
            />
            <label className="text-gray-500">到</label>
            <input
              type="date"
              value={tbParams.date_to ?? ''}
              onChange={e => setTbParams({ date_to: e.target.value })}
              className="border border-gray-300 rounded px-2 py-1 text-sm"
            />
          </div>

          {/* 隐藏零余额 */}
          <label className="flex items-center gap-1 text-sm text-gray-600 cursor-pointer">
            <input
              type="checkbox"
              checked={tbParams.hide_zero ?? false}
              onChange={e => setTbParams({ hide_zero: e.target.checked })}
              className="rounded"
            />
            隐藏无发生额零余额科目
          </label>

          {/* 高级筛选气泡 */}
          <div className="relative" ref={filterRef}>
            <button
              onClick={() => setFilterOpen(v => !v)}
              className="px-3 py-1.5 text-sm border border-gray-300 rounded hover:bg-gray-50 flex items-center gap-1"
            >
              高级筛选
              <span className="text-xs">{filterOpen ? '▲' : '▼'}</span>
            </button>

            {filterOpen && (
              <div className="absolute left-0 top-full mt-1 z-50 bg-white border border-gray-200 rounded-lg shadow-lg p-4 w-72">
                <p className="text-xs font-medium text-gray-700 mb-3">高级筛选</p>
                <div className="flex flex-col gap-3">
                  <div className="flex flex-col gap-1">
                    <label className="text-xs text-gray-500">起始科目编码</label>
                    <input
                      type="text" placeholder="如 1001"
                      value={draftStartCode}
                      onChange={e => setDraftStartCode(e.target.value)}
                      className="border border-gray-300 rounded px-2 py-1 text-sm"
                    />
                  </div>
                  <div className="flex flex-col gap-1">
                    <label className="text-xs text-gray-500">截止科目编码</label>
                    <input
                      type="text" placeholder="如 5999"
                      value={draftEndCode}
                      onChange={e => setDraftEndCode(e.target.value)}
                      className="border border-gray-300 rounded px-2 py-1 text-sm"
                    />
                  </div>
                  <NumberInput
                    label="科目级别（最深显示到第几级）"
                    value={draftMaxLevel}
                    onChange={setDraftMaxLevel}
                  />
                  <button
                    onClick={applyFilter}
                    className="mt-1 w-full py-1.5 bg-primary-600 text-white text-sm rounded hover:bg-primary-700"
                  >
                    应用筛选
                  </button>
                </div>
              </div>
            )}
          </div>

          {/* 查询按钮 */}
          <button
            onClick={() => load()}
            disabled={tbLoading}
            className="px-4 py-1.5 bg-primary-600 text-white text-sm rounded hover:bg-primary-700 disabled:opacity-50"
          >
            {tbLoading ? '查询中…' : '查询'}
          </button>
        </div>

        {/* 右侧：打印 / 导出 */}
        <div className="flex items-center gap-2">
          <button
            onClick={exportExcel}
            disabled={tbItems.length === 0}
            className="px-3 py-1.5 text-sm border border-gray-300 rounded hover:bg-gray-50 disabled:opacity-40"
          >
            导出 Excel
          </button>
          <button
            onClick={handlePrint}
            className="px-3 py-1.5 text-sm border border-gray-300 rounded hover:bg-gray-50"
          >
            打印
          </button>
        </div>
      </div>

      {/* ── 试算不平衡警告 ──────────────────────────────────────────── */}
      {!tbBalanced && (
        <div className="mb-3 p-3 bg-red-50 border border-red-400 rounded text-sm text-red-700 font-semibold print:block">
          ⚠️ 试算不平衡！{!tbOpeningBalanced && '期初余额不平 '}
          {!tbCurrentBalanced && '本期发生额不平 '}
          {!tbClosingBalanced && '期末余额不平'}—— 请检查数据完整性。
        </div>
      )}

      {/* ── 错误提示 ─────────────────────────────────────────────────── */}
      {tbError && (
        <div className="mb-3 p-3 bg-red-50 border border-red-300 rounded text-sm text-red-600">
          {tbError}
        </div>
      )}

      {/* ── 表格 ─────────────────────────────────────────────────────── */}
      <div className="overflow-x-auto border border-gray-200 rounded-lg print:border-0">
        <table className="min-w-full text-sm border-collapse">
          {/* 多级表头 */}
          <thead className="bg-gray-50 print:bg-gray-100">
            <tr>
              <th rowSpan={2} className="border border-gray-200 px-3 py-2 text-left font-medium text-gray-700 w-28">
                科目编码
              </th>
              <th rowSpan={2} className="border border-gray-200 px-3 py-2 text-left font-medium text-gray-700 min-w-40">
                科目名称
              </th>
              <th colSpan={2} className="border border-gray-200 px-3 py-2 text-center font-medium text-gray-700">
                期初余额
              </th>
              <th colSpan={2} className="border border-gray-200 px-3 py-2 text-center font-medium text-gray-700">
                本期发生额
              </th>
              <th colSpan={2} className="border border-gray-200 px-3 py-2 text-center font-medium text-gray-700">
                期末余额
              </th>
            </tr>
            <tr>
              <th className="border border-gray-200 px-3 py-1.5 text-right font-medium text-gray-600 w-32">借方</th>
              <th className="border border-gray-200 px-3 py-1.5 text-right font-medium text-gray-600 w-32">贷方</th>
              <th className="border border-gray-200 px-3 py-1.5 text-right font-medium text-gray-600 w-32">借方</th>
              <th className="border border-gray-200 px-3 py-1.5 text-right font-medium text-gray-600 w-32">贷方</th>
              <th className="border border-gray-200 px-3 py-1.5 text-right font-medium text-gray-600 w-32">借方</th>
              <th className="border border-gray-200 px-3 py-1.5 text-right font-medium text-gray-600 w-32">贷方</th>
            </tr>
          </thead>

          <tbody>
            {tbLoading && (
              <tr>
                <td colSpan={8} className="text-center py-12 text-gray-400">
                  加载中…
                </td>
              </tr>
            )}

            {!tbLoading && tbItems.length === 0 && (
              <tr>
                <td colSpan={8} className="text-center py-12 text-gray-400">
                  暂无数据
                </td>
              </tr>
            )}

            {!tbLoading && tbItems.map(item => (
              <TrialBalanceRow key={item.code} item={item} />
            ))}
          </tbody>

          {/* 合计行 */}
          {!tbLoading && tbTotals && tbItems.length > 0 && (
            <tfoot>
              <tr className="bg-gray-50 font-bold border-t-2 border-gray-300">
                <td className="border border-gray-200 px-3 py-2" colSpan={2}>合计</td>
                <td className="border border-gray-200 px-3 py-2 text-right tabular-nums">
                  {fmtTotal(tbTotals.opening_debit)}
                </td>
                <td className="border border-gray-200 px-3 py-2 text-right tabular-nums">
                  {fmtTotal(tbTotals.opening_credit)}
                </td>
                <td className="border border-gray-200 px-3 py-2 text-right tabular-nums">
                  {fmtTotal(tbTotals.current_debit)}
                </td>
                <td className="border border-gray-200 px-3 py-2 text-right tabular-nums">
                  {fmtTotal(tbTotals.current_credit)}
                </td>
                <td className="border border-gray-200 px-3 py-2 text-right tabular-nums">
                  {fmtTotal(tbTotals.closing_debit)}
                </td>
                <td className="border border-gray-200 px-3 py-2 text-right tabular-nums">
                  {fmtTotal(tbTotals.closing_credit)}
                </td>
              </tr>
            </tfoot>
          )}
        </table>
      </div>

      {/* 打印页脚 */}
      <div className="hidden print:block mt-4 text-xs text-gray-500 text-center">
        AgentLedger — 科目余额表 &nbsp;|&nbsp; 期间：{tbParams.date_from} ～ {tbParams.date_to}
      </div>
    </div>
  )
}

// ── 单行组件 ──────────────────────────────────────────────────────────────
function TrialBalanceRow({ item }: { item: TrialBalanceItem }) {
  const indent   = (item.level - 1) * 20
  const isBold   = item.level === 1
  const redOpen  = isReversed(item, 'opening')
  const redClose = isReversed(item, 'closing')

  return (
    <tr className="hover:bg-blue-50/40 transition-colors">
      {/* 科目编码 */}
      <td className="border border-gray-100 px-3 py-1.5 text-gray-600 font-mono text-xs">
        {item.code}
      </td>

      {/* 科目名称（缩进 + 1级加粗） */}
      <td
        className={`border border-gray-100 py-1.5 pr-3 ${isBold ? 'font-semibold text-gray-800' : 'text-gray-700'}`}
        style={{ paddingLeft: `${12 + indent}px` }}
      >
        {item.name}
      </td>

      {/* 期初余额借方 */}
      <td className={`border border-gray-100 px-3 py-1.5 text-right tabular-nums ${redOpen ? 'text-red-500' : 'text-gray-800'}`}>
        {fmt(item.opening_debit)}
      </td>

      {/* 期初余额贷方 */}
      <td className={`border border-gray-100 px-3 py-1.5 text-right tabular-nums ${redOpen ? 'text-red-500' : 'text-gray-800'}`}>
        {fmt(item.opening_credit)}
      </td>

      {/* 本期借方 */}
      <td className="border border-gray-100 px-3 py-1.5 text-right tabular-nums text-gray-800">
        {fmt(item.current_debit)}
      </td>

      {/* 本期贷方 */}
      <td className="border border-gray-100 px-3 py-1.5 text-right tabular-nums text-gray-800">
        {fmt(item.current_credit)}
      </td>

      {/* 期末余额借方 */}
      <td className={`border border-gray-100 px-3 py-1.5 text-right tabular-nums ${redClose ? 'text-red-500' : 'text-gray-800'}`}>
        {fmt(item.closing_debit)}
      </td>

      {/* 期末余额贷方 */}
      <td className={`border border-gray-100 px-3 py-1.5 text-right tabular-nums ${redClose ? 'text-red-500' : 'text-gray-800'}`}>
        {fmt(item.closing_credit)}
      </td>
    </tr>
  )
}
