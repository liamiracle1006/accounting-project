import { useState, useRef } from 'react'
import { batchApi } from '@/api/batch'
import { useBatchStore } from '@/store/useBatchStore'
import { useToast } from '@/hooks/useToast'
import { usePoll } from '@/hooks/usePoll'
import { ConfidenceBadge } from '@/components/common/Badge'
import { PageLoader, Spinner } from '@/components/common/Spinner'
import type { StandardReceiptItem } from '@/types'

const fmt = (n: number) => n.toLocaleString('zh-CN', { minimumFractionDigits: 2 })
type Step = 1 | 2 | 3 | 4

export default function BatchImportConsole() {
  const [step, setStep] = useState<Step>(1)
  const [parsing, setParsing] = useState(false)
  const [executing, setExecuting] = useState(false)
  const [voucherWord, setVoucherWord] = useState('记')
  const fileRef = useRef<HTMLInputElement>(null)
  const { files, previewItems, taskId, progress, results,
          setFiles, setPreview, setTaskId, setProgress, setResults, reset } = useBatchStore()
  const { success, error } = useToast()
  const polling = step === 3 && !!taskId && progress?.status !== 'COMPLETED' && progress?.status !== 'FAILED'

  usePoll(async () => {
    if (!taskId) return false
    const p = await batchApi.progress(taskId)
    setProgress(p)
    if (p.status === 'COMPLETED') {
      const r = await batchApi.results(taskId)
      setResults(r)
      setStep(4)
      return true
    }
    if (p.status === 'FAILED') { error('批量处理失败'); return true }
    return false
  }, 2000, polling)

  const handleFiles = (e: React.ChangeEvent<HTMLInputElement>) => {
    const list = Array.from(e.target.files ?? [])
    setFiles(list)
  }

  const parsePreview = async () => {
    if (!files.length) { error('请先选择文件'); return }
    setParsing(true)
    try {
      const data = await batchApi.parsePreview(files)
      setPreview(data.items, data.parse_engine)
      setStep(2)
    } catch (e) {
      error((e as Error).message)
    } finally {
      setParsing(false)
    }
  }

  const [editedItems, setEditedItems] = useState<StandardReceiptItem[] | null>(null)
  const items = editedItems ?? previewItems

  const updateItem = (idx: number, key: keyof StandardReceiptItem, val: unknown) => {
    const copy = items.map((it, i) => i === idx ? { ...it, [key]: val } : it)
    setEditedItems(copy)
  }
  const removeItem = (idx: number) => setEditedItems(items.filter((_, i) => i !== idx))

  const execute = async () => {
    if (!items.length) { error('票据列表为空'); return }
    setExecuting(true)
    try {
      const resp = await batchApi.execute({ items, voucher_word: voucherWord })
      setTaskId(resp.task_id)
      setStep(3)
    } catch (e) {
      error((e as Error).message)
    } finally {
      setExecuting(false)
    }
  }

  const handleReset = () => { reset(); setStep(1); setEditedItems(null) }

  const pct = progress && progress.total_count > 0
    ? Math.round(((progress.success_count + progress.error_count) / progress.total_count) * 100)
    : 0

  return (
    <div className="p-6 max-w-4xl">
      <h1 className="text-xl font-bold text-slate-800 mb-5">批量导入</h1>

      {/* 步骤指示 */}
      <div className="flex items-center gap-2 mb-6 text-xs">
        {(['① 选择文件', '② 核对', '③ 处理中', '④ 结果'] as const).map((label, i) => (
          <span key={i} className={`px-3 py-1 rounded-full ${step === i + 1 ? 'bg-primary-100 text-primary-700 font-semibold' : 'text-slate-400'}`}>
            {label}
          </span>
        ))}
      </div>

      {/* 步骤1：上传 */}
      {step === 1 && (
        <div className="bg-white border border-slate-200 rounded-xl p-6">
          <p className="text-sm text-slate-500 mb-4">
            支持格式：Excel (.xlsx/.xls/.csv) · 图片 (.jpg/.png/.webp) · PDF（可混合上传）
          </p>
          <div
            onClick={() => fileRef.current?.click()}
            className="border-2 border-dashed border-slate-300 hover:border-primary-400 rounded-xl p-10 text-center cursor-pointer transition-colors"
          >
            <p className="text-slate-400 text-sm">点击选择文件，或拖拽到此区域</p>
            {files.length > 0 && (
              <p className="mt-2 text-primary-600 font-medium text-sm">已选 {files.length} 个文件</p>
            )}
          </div>
          <input ref={fileRef} type="file" multiple accept=".xlsx,.xls,.csv,.jpg,.jpeg,.png,.webp,.pdf"
            className="hidden" onChange={handleFiles} />
          <div className="mt-4 flex items-center gap-3">
            <div className="flex-1">
              <label className="text-xs text-slate-500 mr-2">凭证字</label>
              <select value={voucherWord} onChange={e => setVoucherWord(e.target.value)}
                className="border border-slate-200 rounded px-2 py-1 text-sm">
                {['记', '收', '付', '转'].map(w => <option key={w}>{w}</option>)}
              </select>
            </div>
            <button
              onClick={parsePreview} disabled={parsing || !files.length}
              className="px-5 py-2 bg-primary-600 hover:bg-primary-700 disabled:bg-slate-300 text-white text-sm rounded-lg font-medium"
            >
              {parsing ? <Spinner size="sm" /> : '解析预览 →'}
            </button>
          </div>
        </div>
      )}

      {/* 步骤2：核对 */}
      {step === 2 && (
        <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
          <div className="px-5 py-3 border-b border-slate-200 flex items-center justify-between">
            <span className="text-sm font-semibold">共 {items.length} 条票据，可修改后提交</span>
            <div className="flex gap-2">
              <button onClick={handleReset} className="text-xs text-slate-500 hover:underline">重新上传</button>
              <button
                onClick={execute} disabled={executing || !items.length}
                className="px-4 py-1.5 bg-primary-600 hover:bg-primary-700 disabled:bg-slate-300 text-white text-xs rounded-lg font-medium"
              >{executing ? '提交中…' : '提交入账 →'}</button>
            </div>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead className="bg-slate-50 text-slate-500">
                <tr>
                  <th className="px-3 py-2 text-left">日期</th>
                  <th className="px-3 py-2 text-right">金额</th>
                  <th className="px-3 py-2 text-left">对方单位</th>
                  <th className="px-3 py-2 text-left">摘要</th>
                  <th className="px-3 py-2 w-6"></th>
                </tr>
              </thead>
              <tbody>
                {items.map((item, idx) => (
                  <tr key={idx} className="border-t border-slate-100">
                    <td className="px-3 py-1.5">
                      <input type="date" value={item.date} onChange={e => updateItem(idx, 'date', e.target.value)}
                        className="border border-slate-200 rounded px-1.5 py-0.5 text-xs" />
                    </td>
                    <td className="px-3 py-1.5 text-right">
                      <input type="number" value={item.amount} step="0.01" min="0.01"
                        onChange={e => updateItem(idx, 'amount', parseFloat(e.target.value))}
                        className="border border-slate-200 rounded px-1.5 py-0.5 text-xs w-24 text-right" />
                    </td>
                    <td className="px-3 py-1.5">
                      <input value={item.counterparty ?? ''} onChange={e => updateItem(idx, 'counterparty', e.target.value || null)}
                        className="border border-slate-200 rounded px-1.5 py-0.5 text-xs w-28" />
                    </td>
                    <td className="px-3 py-1.5">
                      <input value={item.summary} onChange={e => updateItem(idx, 'summary', e.target.value)}
                        className="border border-slate-200 rounded px-1.5 py-0.5 text-xs w-40" />
                    </td>
                    <td className="px-3 py-1.5 text-center">
                      <button onClick={() => removeItem(idx)} className="text-red-400 hover:text-red-600">×</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* 步骤3：进度 */}
      {step === 3 && progress && (
        <div className="bg-white border border-slate-200 rounded-xl p-6 text-center">
          <Spinner size="lg" />
          <p className="mt-4 font-medium text-slate-700">{progress.status === 'PROCESSING' ? 'AI 正在批量入账…' : progress.status}</p>
          <div className="mt-4 max-w-sm mx-auto">
            <div className="h-2 bg-slate-100 rounded-full overflow-hidden">
              <div className="h-full bg-primary-600 rounded-full transition-all" style={{ width: `${pct}%` }} />
            </div>
            <p className="text-xs text-slate-400 mt-1">{progress.success_count + progress.error_count} / {progress.total_count}</p>
          </div>
        </div>
      )}

      {/* 步骤4：结果 */}
      {step === 4 && results && (
        <div className="space-y-4">
          <div className="grid grid-cols-3 gap-4">
            {[
              ['✅ 成功入账', results.success.length - results.needs_review.length, 'bg-green-50 text-green-700'],
              ['⚠️ 需复核', results.needs_review.length, 'bg-amber-50 text-amber-700'],
              ['❌ 失败', results.errors.length, 'bg-red-50 text-red-700'],
            ].map(([label, count, cls]) => (
              <div key={String(label)} className={`rounded-xl p-4 text-center ${cls}`}>
                <p className="text-2xl font-bold">{String(count)}</p>
                <p className="text-sm mt-1">{String(label)}</p>
              </div>
            ))}
          </div>

          {results.errors.length > 0 && (
            <div className="bg-white border border-red-200 rounded-xl overflow-hidden">
              <div className="px-4 py-2.5 bg-red-50 border-b border-red-100 text-sm font-semibold text-red-700">处理失败明细</div>
              {results.errors.map(r => (
                <div key={r.id} className="px-4 py-2 border-t border-slate-100 text-sm">
                  <span className="text-slate-700">{r.raw_data.summary}</span>
                  <span className="ml-2 text-xs text-red-500">{r.error_msg}</span>
                </div>
              ))}
            </div>
          )}

          {results.success.length > 0 && (
            <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
              <div className="px-4 py-2.5 bg-slate-50 border-b border-slate-100 text-sm font-semibold text-slate-700">成功明细</div>
              {results.success.map(r => (
                <div key={r.id} className="px-4 py-2 border-t border-slate-100 text-sm flex items-center gap-3">
                  <span className="text-slate-700 flex-1">{r.raw_data.summary}</span>
                  <span className="text-slate-500">¥{fmt(r.raw_data.amount)}</span>
                  {r.confidence && <ConfidenceBadge level={r.confidence} />}
                  {r.needs_review && <span className="text-xs text-amber-600 font-medium">需复核</span>}
                </div>
              ))}
            </div>
          )}

          <button onClick={handleReset}
            className="px-4 py-2 border border-slate-300 rounded-lg text-sm hover:bg-slate-50">
            重新导入
          </button>
        </div>
      )}
    </div>
  )
}
