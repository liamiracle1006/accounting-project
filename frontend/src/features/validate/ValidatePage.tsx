import { useState } from 'react'
import { api } from '@/api/client'
import type { BalanceSheet, BSLineItem, IncomeStatement } from '@/types'

// ── Types ─────────────────────────────────────────────────────────────────────

interface DiffRow {
  name:      string
  computed:  number
  reference: number
  diff:      number
  match:     boolean
}

interface TBItem {
  code:           string
  name:           string
  level?:         number          // 0=母科目 1=子科目
  parent_code?:   string | null
  has_children?:  boolean
  opening_debit:  number
  opening_credit: number
  current_debit:  number
  current_credit: number
  closing_debit:  number
  closing_credit: number
}

interface TrialBalance {
  items:  TBItem[]
  totals: {
    opening_debit:  number; opening_credit: number
    current_debit:  number; current_credit: number
    closing_debit:  number; closing_credit: number
  }
  balanced: { opening: boolean; current: boolean; closing: boolean }
}

interface TBDiffRow {
  code:          string
  name:          string
  sys_opening:   number; ref_opening: number; opening_match: boolean
  sys_current:   number; ref_current: number; current_match: boolean
  sys_closing:   number; ref_closing: number; closing_match: boolean
  match:         boolean
}

interface ValidateResult {
  balance_sheet:      BalanceSheet
  income_statement:   IncomeStatement
  trial_balance?:     TrialBalance  // 模式 B 才有
  parsed_row_count?:  number       // 模式 A
  baseline_row_count?: number      // 模式 B
  voucher_count?:     number       // 模式 B
  date_from?:         string       // 模式 B
  date_to?:           string       // 模式 B
  column_mapping:     Record<string, string>
  bs_diff:            DiffRow[]
  is_diff:            DiffRow[]
  tb_diff?:           TBDiffRow[]   // 模式 B 上传参考科目余额表后才有
}

type ValidateMode = 'A' | 'B'

const todayStr = (): string => new Date().toISOString().slice(0, 10)
const firstOfMonthStr = (): string => {
  const d = new Date(); d.setDate(1)
  return d.toISOString().slice(0, 10)
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmtNum(n: number, isTotal: boolean): string {
  if (!isTotal && n === 0) return '—'
  return n.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

function fmtDiff(n: number): string {
  if (Math.abs(n) < 0.01) return '✓'
  const s = Math.abs(n).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
  return n > 0 ? `+${s}` : `-${s}`
}

// ── Trial Balance Table ───────────────────────────────────────────────────────

function TBTable({ tb }: { tb: TrialBalance }) {
  const fmtCell = (n: number) => n === 0
    ? <span className="text-gray-300">—</span>
    : n.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
  const t = tb.totals
  const balRow = (label: string, ok: boolean) =>
    <span className={`text-xs px-2 py-0.5 rounded font-medium ${ok ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'}`}>
      {label}{ok ? ' ✓' : ' ✗'}
    </span>

  // 树形展开：默认全部折叠，记录已展开的母科目码
  const parentsWithKids = tb.items.filter(it => it.has_children).map(it => it.code)
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const allExpanded = parentsWithKids.length > 0 && expanded.size === parentsWithKids.length
  const toggle = (code: string) => setExpanded(prev => {
    const next = new Set(prev)
    next.has(code) ? next.delete(code) : next.add(code)
    return next
  })
  const toggleAll = () => setExpanded(allExpanded ? new Set() : new Set(parentsWithKids))

  // 只显示母科目行 + 已展开母科目下的子行
  const visibleItems = tb.items.filter(it =>
    (it.level ?? 0) === 0 || expanded.has(it.parent_code ?? ''))
  const parentCount = tb.items.filter(it => (it.level ?? 0) === 0).length
  const subCount    = tb.items.length - parentCount

  return (
    <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
      <div className="px-4 py-3 border-b border-gray-100 bg-gray-50 flex items-center gap-2 flex-wrap">
        <h3 className="text-sm font-bold text-gray-700">系统反推科目余额表（年累视图）</h3>
        <span className="text-xs text-gray-400">期初=年初 · 本期发生额=全年累计 · 期末=当期末</span>
        {balRow('期初平衡', tb.balanced.opening)}
        {balRow('本期平衡', tb.balanced.current)}
        {balRow('期末平衡', tb.balanced.closing)}
        {parentsWithKids.length > 0 && (
          <button onClick={toggleAll}
            className="text-xs px-2 py-0.5 rounded border border-gray-300 text-gray-600 hover:bg-gray-100">
            {allExpanded ? '收起全部子科目' : '展开全部子科目'}
          </button>
        )}
        <span className="text-xs text-gray-400 ml-auto">{parentCount} 个母科目 · {subCount} 个子科目</span>
      </div>
      <div className="overflow-auto max-h-[600px]">
        <table className="w-full text-xs border-collapse">
          <thead className="sticky top-0 bg-gray-50 z-10">
            <tr className="text-gray-500">
              <th rowSpan={2} className="border border-gray-200 px-2 py-1 text-left">科目</th>
              <th colSpan={2} className="border border-gray-200 px-2 py-1 text-center">期初余额</th>
              <th colSpan={2} className="border border-gray-200 px-2 py-1 text-center">本期发生额</th>
              <th colSpan={2} className="border border-gray-200 px-2 py-1 text-center">期末余额</th>
            </tr>
            <tr className="text-gray-500">
              <th className="border border-gray-200 px-2 py-1 text-right">借方</th>
              <th className="border border-gray-200 px-2 py-1 text-right">贷方</th>
              <th className="border border-gray-200 px-2 py-1 text-right">借方</th>
              <th className="border border-gray-200 px-2 py-1 text-right">贷方</th>
              <th className="border border-gray-200 px-2 py-1 text-right">借方</th>
              <th className="border border-gray-200 px-2 py-1 text-right">贷方</th>
            </tr>
          </thead>
          <tbody>
            {visibleItems.map(it => {
              const isChild = (it.level ?? 0) > 0
              return (
                <tr key={it.code} className={isChild ? 'bg-slate-50/60' : 'hover:bg-gray-50'}>
                  <td className="border border-gray-200 px-2 py-1">
                    {isChild ? (
                      <span className="pl-6 text-gray-600">
                        <span className="font-mono text-gray-400 mr-1">{it.code}</span>
                        {it.name}
                      </span>
                    ) : (
                      <span>
                        {it.has_children ? (
                          <button onClick={() => toggle(it.code)}
                            className="mr-1 text-gray-400 hover:text-gray-700 w-3 inline-block">
                            {expanded.has(it.code) ? '▼' : '▶'}
                          </button>
                        ) : <span className="mr-1 w-3 inline-block" />}
                        <span className="font-mono text-gray-500 mr-1">{it.code}</span>
                        <span className="text-gray-800 font-medium">{it.name}</span>
                      </span>
                    )}
                  </td>
                  <td className="border border-gray-200 px-2 py-1 text-right tabular-nums">{fmtCell(it.opening_debit)}</td>
                  <td className="border border-gray-200 px-2 py-1 text-right tabular-nums">{fmtCell(it.opening_credit)}</td>
                  <td className="border border-gray-200 px-2 py-1 text-right tabular-nums">{fmtCell(it.current_debit)}</td>
                  <td className="border border-gray-200 px-2 py-1 text-right tabular-nums">{fmtCell(it.current_credit)}</td>
                  <td className="border border-gray-200 px-2 py-1 text-right tabular-nums">{fmtCell(it.closing_debit)}</td>
                  <td className="border border-gray-200 px-2 py-1 text-right tabular-nums">{fmtCell(it.closing_credit)}</td>
                </tr>
              )
            })}
            <tr className="bg-gray-100 font-semibold sticky bottom-0">
              <td className="border border-gray-300 px-2 py-1.5">合计</td>
              <td className="border border-gray-300 px-2 py-1.5 text-right tabular-nums">{fmtCell(t.opening_debit)}</td>
              <td className="border border-gray-300 px-2 py-1.5 text-right tabular-nums">{fmtCell(t.opening_credit)}</td>
              <td className="border border-gray-300 px-2 py-1.5 text-right tabular-nums">{fmtCell(t.current_debit)}</td>
              <td className="border border-gray-300 px-2 py-1.5 text-right tabular-nums">{fmtCell(t.current_credit)}</td>
              <td className="border border-gray-300 px-2 py-1.5 text-right tabular-nums">{fmtCell(t.closing_debit)}</td>
              <td className="border border-gray-300 px-2 py-1.5 text-right tabular-nums">{fmtCell(t.closing_credit)}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  )
}

// ── Trial Balance Diff Table ──────────────────────────────────────────────────

function TBDiffTable({ rows }: { rows: TBDiffRow[] }) {
  if (rows.length === 0) return null
  const mismatches = rows.filter(r => !r.match)
  const f = (n: number) => n.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
  const cell = (v: number, ok: boolean, bold = false) =>
    <td className={`border border-gray-200 px-2 py-1 text-right tabular-nums ${
      ok ? 'text-gray-700' : `bg-red-50 text-red-700 ${bold ? 'font-semibold' : ''}`}`}>{f(v)}</td>
  return (
    <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
      <div className="px-4 py-3 border-b border-gray-100 bg-gray-50 flex items-center gap-3">
        <h3 className="text-sm font-bold text-gray-700">科目余额表 — 与参考表差异对比</h3>
        {mismatches.length === 0
          ? <span className="text-xs bg-green-100 text-green-700 px-2 py-0.5 rounded-full font-medium">全部一致 ✓</span>
          : <span className="text-xs bg-red-100 text-red-700 px-2 py-0.5 rounded-full font-medium">{mismatches.length} 个科目对不上</span>}
        <span className="text-xs text-gray-400 ml-auto">共比对 {rows.length} 个科目（净额，差 ≥1 元标红）</span>
      </div>
      {mismatches.length > 0 && (
        <div className="overflow-auto max-h-[500px]">
          <table className="w-full text-xs border-collapse">
            <thead className="sticky top-0 bg-gray-50 z-10">
              <tr className="text-gray-500">
                <th rowSpan={2} className="border border-gray-200 px-2 py-1 text-left">科目</th>
                <th colSpan={2} className="border border-gray-200 px-2 py-1 text-center">期初净额</th>
                <th colSpan={2} className="border border-gray-200 px-2 py-1 text-center">本期发生净额</th>
                <th colSpan={2} className="border border-gray-200 px-2 py-1 text-center">期末净额</th>
              </tr>
              <tr className="text-gray-400">
                <th className="border border-gray-200 px-2 py-1">系统</th><th className="border border-gray-200 px-2 py-1">参考</th>
                <th className="border border-gray-200 px-2 py-1">系统</th><th className="border border-gray-200 px-2 py-1">参考</th>
                <th className="border border-gray-200 px-2 py-1">系统</th><th className="border border-gray-200 px-2 py-1">参考</th>
              </tr>
            </thead>
            <tbody>
              {mismatches.map(r => (
                <tr key={r.code}>
                  <td className="border border-gray-200 px-2 py-1">
                    <span className="font-mono text-gray-500 mr-1">{r.code}</span>{r.name}
                  </td>
                  {cell(r.sys_opening, r.opening_match, true)}{cell(r.ref_opening, r.opening_match)}
                  {cell(r.sys_current, r.current_match, true)}{cell(r.ref_current, r.current_match)}
                  {cell(r.sys_closing, r.closing_match, true)}{cell(r.ref_closing, r.closing_match)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

// ── Diff Table ────────────────────────────────────────────────────────────────

function DiffTable({ title, rows }: { title: string; rows: DiffRow[] }) {
  if (rows.length === 0) return null
  const mismatches = rows.filter(r => !r.match).length
  return (
    <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
      <div className="px-4 py-3 border-b border-gray-100 bg-gray-50 flex items-center gap-3">
        <h3 className="text-sm font-bold text-gray-700">{title} — 差异对比</h3>
        {mismatches === 0
          ? <span className="text-xs bg-green-100 text-green-700 px-2 py-0.5 rounded-full font-medium">全部一致 ✓</span>
          : <span className="text-xs bg-red-100 text-red-700 px-2 py-0.5 rounded-full font-medium">{mismatches} 项有差异</span>
        }
        <span className="text-xs text-gray-400">共匹配 {rows.length} 行</span>
      </div>
      <div className="overflow-auto">
        <table className="w-full text-sm border-collapse">
          <thead>
            <tr className="bg-gray-50 text-xs text-gray-500">
              <th className="border border-gray-200 px-3 py-2 text-left w-[40%]">行项目</th>
              <th className="border border-gray-200 px-3 py-2 text-right">系统计算</th>
              <th className="border border-gray-200 px-3 py-2 text-right">参考Excel</th>
              <th className="border border-gray-200 px-3 py-2 text-right w-32">差额</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row, idx) => (
              <tr key={idx} className={row.match ? 'bg-green-50/40' : 'bg-red-50'}>
                <td className="border border-gray-200 px-3 py-1.5 text-gray-700">{row.name}</td>
                <td className="border border-gray-200 px-3 py-1.5 text-right tabular-nums text-gray-800">
                  {row.computed.toLocaleString('zh-CN', { minimumFractionDigits: 2 })}
                </td>
                <td className="border border-gray-200 px-3 py-1.5 text-right tabular-nums text-gray-600">
                  {row.reference.toLocaleString('zh-CN', { minimumFractionDigits: 2 })}
                </td>
                <td className={`border border-gray-200 px-3 py-1.5 text-right tabular-nums font-medium ${
                  row.match ? 'text-green-600' : 'text-red-600'
                }`}>
                  {fmtDiff(row.diff)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

// ── BS Table ─────────────────────────────────────────────────────────────────

function BSSection({ title, items }: { title: string; items: BSLineItem[] }) {
  return (
    <div className="flex-1 min-w-0">
      <table className="w-full text-sm border-collapse">
        <thead>
          <tr className="bg-gray-50">
            <th className="border border-gray-200 px-3 py-2 text-left font-medium text-gray-600 w-[48%]">{title}</th>
            <th className="border border-gray-200 px-3 py-2 text-right font-medium text-gray-600">期末余额</th>
            <th className="border border-gray-200 px-3 py-2 text-right font-medium text-gray-600">年初余额</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item, idx) => (
            <tr key={idx} className={item.is_total ? 'bg-gray-50 font-semibold' : 'hover:bg-blue-50/30'}>
              <td className={`border border-gray-200 px-3 py-1.5 text-gray-700 ${item.is_total ? '' : 'pl-5'}`}>
                {item.name}
              </td>
              <td className={`border border-gray-200 px-3 py-1.5 text-right tabular-nums ${item.end_bal < 0 ? 'text-red-600' : 'text-gray-800'}`}>
                {fmtNum(item.end_bal, item.is_total)}
              </td>
              <td className={`border border-gray-200 px-3 py-1.5 text-right tabular-nums ${item.beg_bal < 0 ? 'text-red-600' : 'text-gray-800'}`}>
                {fmtNum(item.beg_bal, item.is_total)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ── IS Table ─────────────────────────────────────────────────────────────────

function ISTable({ is }: { is: IncomeStatement }) {
  const { items, col1_label = '本期金额', col2_label = '上期金额' } = is
  const hasRowNum = items.some(it => it.row_num > 0)
  return (
    <table className="w-full text-sm border-collapse">
      <thead>
        <tr className="bg-gray-50">
          {hasRowNum && (
            <th className="border border-gray-200 px-2 py-2 text-center font-medium text-gray-600 w-10">行次</th>
          )}
          <th className="border border-gray-200 px-3 py-2 text-left font-medium text-gray-600">项目</th>
          <th className="border border-gray-200 px-3 py-2 text-right font-medium text-gray-600 w-40">{col1_label}</th>
          <th className="border border-gray-200 px-3 py-2 text-right font-medium text-gray-600 w-40">{col2_label}</th>
        </tr>
      </thead>
      <tbody>
        {items.map((item, idx) => {
          const isNetProfit = item.name.includes('净利润') && item.is_total
          return (
            <tr key={idx} className={
              isNetProfit ? 'bg-green-50 font-bold text-green-800'
              : item.is_total ? 'bg-gray-50 font-semibold'
              : 'hover:bg-blue-50/30'
            }>
              {hasRowNum && (
                <td className="border border-gray-200 px-2 py-1.5 text-center text-gray-400 text-xs">
                  {item.row_num > 0 ? item.row_num : ''}
                </td>
              )}
              <td className={`border border-gray-200 px-3 py-1.5 text-gray-700 ${
                item.is_total ? '' : item.name.startsWith('  ') ? 'pl-8'
                : item.name.startsWith('减：') || item.name.startsWith('加：') ? 'pl-6' : 'pl-3'
              }`}>
                {item.name}
              </td>
              <td className={`border border-gray-200 px-3 py-1.5 text-right tabular-nums ${item.cur_amt < 0 ? 'text-red-600' : 'text-gray-800'}`}>
                {fmtNum(item.cur_amt, item.is_total)}
              </td>
              <td className="border border-gray-200 px-3 py-1.5 text-right tabular-nums text-gray-400">
                {item.prev_amt === 0 ? '—' : fmtNum(item.prev_amt, item.is_total)}
              </td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}

// ── File Input ────────────────────────────────────────────────────────────────

function FileInput({
  label, hint, value, onChange,
}: {
  label: string
  hint:  string
  value: File | null
  onChange: (f: File | null) => void
}) {
  return (
    <div className="flex flex-col gap-1">
      <label className="text-xs text-gray-500">{label}</label>
      <input
        type="file"
        accept=".xlsx,.xls"
        onChange={e => onChange(e.target.files?.[0] ?? null)}
        className="text-xs text-gray-600 file:mr-2 file:py-1 file:px-2 file:rounded file:border-0 file:text-xs file:font-medium file:bg-gray-100 file:text-gray-600 hover:file:bg-gray-200"
      />
      {value && <span className="text-xs text-gray-400">{value.name}</span>}
      {!value && <span className="text-xs text-gray-300">{hint}</span>}
    </div>
  )
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function ValidatePage() {
  const [mode,      setMode]      = useState<ValidateMode>('A')
  const [tbFile,    setTbFile]    = useState<File | null>(null)
  const [monthFile, setMonthFile] = useState<File | null>(null)
  const [bsRefFile, setBsRefFile] = useState<File | null>(null)
  const [isRefFile, setIsRefFile] = useState<File | null>(null)
  const [tbRefFile, setTbRefFile] = useState<File | null>(null)
  const [dateFrom,  setDateFrom]  = useState<string>(firstOfMonthStr())
  const [dateTo,    setDateTo]    = useState<string>(todayStr())
  const [standard,  setStandard]  = useState<'xiye' | 'gaap'>('xiye')
  const [loading,   setLoading]   = useState(false)
  const [error,     setError]     = useState<string | null>(null)
  const [result,    setResult]    = useState<ValidateResult | null>(null)

  async function handleCompute() {
    // 模式 A 必须有科目表文件；模式 B 基准表可选（开账首月留空）
    if (mode === 'A' && !tbFile) return
    setLoading(true)
    setError(null)
    try {
      const form = new FormData()
      if (mode === 'A') {
        form.append('file', tbFile!)
        if (monthFile) form.append('month_file', monthFile)
        if (bsRefFile) form.append('bs_ref', bsRefFile)
        if (isRefFile) form.append('is_ref', isRefFile)
        form.append('standard', standard)

        const resp = await fetch('/api/validate/trial-balance', { method: 'POST', body: form })
        if (!resp.ok) {
          const body = await resp.json().catch(() => ({}))
          throw new Error(body.detail ?? `HTTP ${resp.status}`)
        }
        setResult(await resp.json())
      } else {
        // 模式 B：基准 + 系统凭证（需鉴权，用 api.post 自动带 token）
        if (!dateFrom || !dateTo) { setError('请填写日期范围'); return }
        if (tbFile) form.append('baseline_file', tbFile)  // 不传=开账首月，期初当 0
        form.append('date_from', dateFrom)
        form.append('date_to',   dateTo)
        if (bsRefFile) form.append('bs_ref', bsRefFile)
        if (isRefFile) form.append('is_ref', isRefFile)
        if (tbRefFile) form.append('tb_ref', tbRefFile)
        form.append('standard', standard)
        const resp = await api.post<ValidateResult>('/api/validate/from-vouchers', form)
        setResult(resp)
      }
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }

  const liabAndEquity = result
    ? [...result.balance_sheet.liabilities, ...result.balance_sheet.equity]
    : []

  const hasDiff = result && (result.bs_diff.length > 0 || result.is_diff.length > 0)
  const totalMismatches = result
    ? result.bs_diff.filter(r => !r.match).length + result.is_diff.filter(r => !r.match).length
    : 0

  return (
    <div className="flex flex-col gap-4 p-4 h-full overflow-auto">

      {/* Header */}
      <div className="flex items-center gap-2">
        <span className="bg-yellow-100 text-yellow-800 text-xs font-semibold px-2 py-0.5 rounded">DEV</span>
        <h1 className="text-base font-bold text-gray-800">报表验证工具</h1>
        <span className="text-xs text-gray-400">
          {mode === 'A'
            ? '上传科目余额表 → 算 BS/IS（可对比参考报表）'
            : '上传上期期末科目表 + 选日期范围 → 用系统已过账凭证算本期 BS/IS'}
        </span>
      </div>

      {/* Mode toggle */}
      <div className="flex items-center gap-2 text-sm">
        <span className="text-xs text-gray-500">验证模式：</span>
        {([
          ['A', '模式 A · 单文件科目表'],
          ['B', '模式 B · 基准 + 系统凭证'],
        ] as const).map(([m, label]) => (
          <button
            key={m}
            onClick={() => { setMode(m); setResult(null); setError(null) }}
            className={`px-3 py-1 rounded-lg text-xs font-medium transition-colors ${
              mode === m ? 'bg-blue-600 text-white' : 'bg-white border border-gray-200 text-gray-600 hover:border-blue-400'
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {/* Upload Toolbar */}
      <div className="bg-white rounded-xl border border-gray-200 px-4 py-4 flex flex-wrap items-end gap-5">
        {mode === 'A' ? (
          <>
            <FileInput
              label="年度余额表 1-12月（必填）"
              hint="提供 BS 余额、IS 本年累计"
              value={tbFile}
              onChange={setTbFile}
            />
            <FileInput
              label="单月余额表（可选）"
              hint="提供 IS 本月金额，如 12 月单月"
              value={monthFile}
              onChange={setMonthFile}
            />
          </>
        ) : (
          <>
            <FileInput
              label="上期期末科目表（开账首月可不传）"
              hint="如 11 月期末作基准；首月留空则期初=0"
              value={tbFile}
              onChange={setTbFile}
            />
            <div className="flex flex-col gap-1">
              <label className="text-xs text-gray-500">本期起始日</label>
              <input type="date" value={dateFrom} onChange={e => setDateFrom(e.target.value)}
                className="border border-gray-200 rounded-lg px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
            </div>
            <div className="flex flex-col gap-1">
              <label className="text-xs text-gray-500">本期截止日</label>
              <input type="date" value={dateTo} onChange={e => setDateTo(e.target.value)}
                className="border border-gray-200 rounded-lg px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
            </div>
            <FileInput
              label="参考科目余额表 Excel（可选）"
              hint="当期原系统科目余额表，逐科目对比标红差异"
              value={tbRefFile}
              onChange={setTbRefFile}
            />
          </>
        )}
        <div className="flex flex-col gap-1">
          <label className="text-xs text-gray-500">会计准则</label>
          <div className="flex gap-3 items-center h-8">
            {(['xiye', 'gaap'] as const).map(s => (
              <label key={s} className="flex items-center gap-1.5 cursor-pointer text-sm text-gray-700">
                <input
                  type="radio"
                  name="validate-standard"
                  value={s}
                  checked={standard === s}
                  onChange={() => setStandard(s)}
                  className="accent-blue-600"
                />
                {s === 'gaap' ? '企业准则（2006）' : '小企业准则（2013）'}
              </label>
            ))}
          </div>
        </div>
        <div className="w-px h-10 bg-gray-200 hidden sm:block" />
        <FileInput
          label="参考资产负债表 Excel（可选）"
          hint="上传后自动对比差异"
          value={bsRefFile}
          onChange={setBsRefFile}
        />
        <FileInput
          label="参考利润表 Excel（可选）"
          hint="上传后自动对比差异"
          value={isRefFile}
          onChange={setIsRefFile}
        />
        <button
          onClick={handleCompute}
          disabled={loading || (mode === 'A' && !tbFile)}
          className="px-4 py-2 rounded bg-blue-600 text-white text-sm font-medium hover:bg-blue-700 transition-colors disabled:opacity-50"
        >
          {loading ? '计算中…' : '计算报表'}
        </button>
      </div>

      {/* Mode B 计算说明 */}
      {mode === 'B' && result && (
        <div className="bg-blue-50 border border-blue-200 rounded-lg px-4 py-2 text-xs text-blue-800 flex items-center gap-3 flex-wrap">
          <span>📅 本期：{result.date_from} → {result.date_to}</span>
          <span>📋 基准科目数：{result.baseline_row_count}</span>
          <span>📜 聚合凭证数：{result.voucher_count}（仅 POSTED 状态）</span>
        </div>
      )}

      {/* Column Mapping Debug */}
      {result && (
        <div className="bg-gray-50 border border-gray-200 rounded-lg px-4 py-2 text-xs text-gray-500 flex flex-wrap gap-3">
          <span className="font-medium text-gray-600">科目余额表列映射：</span>
          {Object.entries(result.column_mapping).map(([field, col]) => (
            <span key={field}>
              <span className="text-gray-400">{field}</span>
              <span className="mx-1 text-gray-300">=</span>
              <span className="text-gray-700">"{col}"</span>
            </span>
          ))}
          <span className="text-gray-400">· 识别到 {result.parsed_row_count ?? result.baseline_row_count} 条科目</span>
        </div>
      )}

      {/* Error */}
      {error && (
        <div className="bg-red-50 border border-red-300 text-red-700 text-sm rounded-lg px-4 py-3 whitespace-pre-wrap">
          {error}
        </div>
      )}

      {result && (
        <>
          {/* Balance check + diff summary */}
          <div className="flex flex-wrap gap-3">
            {result.balance_sheet.balanced
              ? <div className="bg-green-50 border border-green-300 text-green-800 text-sm rounded-lg px-4 py-2 font-medium">✅ 资产负债表试算平衡</div>
              : <div className="bg-red-50 border border-red-400 text-red-800 text-sm rounded-lg px-4 py-2 font-medium">
                  ⚠️ 试算不平衡，差额：{Math.abs(result.balance_sheet.diff).toLocaleString('zh-CN', { minimumFractionDigits: 2 })} 元
                </div>
            }
            {hasDiff && (totalMismatches === 0
              ? <div className="bg-green-50 border border-green-300 text-green-800 text-sm rounded-lg px-4 py-2 font-medium">✅ 与参考Excel完全一致</div>
              : <div className="bg-red-50 border border-red-400 text-red-800 text-sm rounded-lg px-4 py-2 font-medium">⚠️ 与参考Excel有 {totalMismatches} 项差异</div>
            )}
          </div>

          {/* Diff tables — show first if there are mismatches */}
          {hasDiff && (
            <div className="flex flex-col gap-3">
              <DiffTable title="资产负债表" rows={result.bs_diff} />
              <DiffTable title="利润表" rows={result.is_diff} />
            </div>
          )}

          {/* 科目余额表与参考表差异（上传参考科目余额表后才有） */}
          {result.tb_diff && result.tb_diff.length > 0 && <TBDiffTable rows={result.tb_diff} />}

          {/* 系统反推科目余额表（仅模式 B 有） */}
          {result.trial_balance && <TBTable tb={result.trial_balance} />}

          {/* Computed reports */}
          <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
            <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
              <div className="px-4 py-3 border-b border-gray-100 bg-gray-50">
                <h2 className="text-sm font-bold text-gray-700">资产负债表（系统计算）</h2>
              </div>
              <div className="overflow-auto">
                <div className="flex min-w-[700px]">
                  <BSSection title="资产" items={result.balance_sheet.assets} />
                  <div className="w-px bg-gray-200 shrink-0" />
                  <BSSection title="负债及所有者权益" items={liabAndEquity} />
                </div>
              </div>
            </div>

            <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
              <div className="px-4 py-3 border-b border-gray-100 bg-gray-50">
                <h2 className="text-sm font-bold text-gray-700">利润表（系统计算）</h2>
                <p className="text-xs text-gray-400 mt-0.5">科目余额表无上期数据，上期列为空</p>
              </div>
              <div className="overflow-auto">
                <ISTable is={result.income_statement} />
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  )
}
