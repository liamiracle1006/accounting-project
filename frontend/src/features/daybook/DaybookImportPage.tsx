import { useState, useRef } from 'react'
import { api } from '@/api/client'
import { useToast } from '@/hooks/useToast'

interface ImportError {
  voucher_no: string
  reason:     string
  rows:       Record<string, string>[]
}

interface ImportResponse {
  total_rows:       number
  parsed_vouchers:  number
  created_vouchers: number
  error_count:      number
  column_mapping:   Record<string, string>
  errors:           ImportError[]
}

export default function DaybookImportPage() {
  const [file, setFile] = useState<File | null>(null)
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<ImportResponse | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)
  const { success, error } = useToast()

  const handleSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0] ?? null
    setFile(f)
    setResult(null)
  }

  const submit = async () => {
    if (!file) { error('请先选择 Excel 文件'); return }
    setLoading(true)
    try {
      const form = new FormData()
      form.append('file', file)
      form.append('standard', 'xiye')
      const resp = await api.post<ImportResponse>('/api/daybook/import', form)
      setResult(resp)
      if (resp.error_count === 0) {
        success(`成功导入 ${resp.created_vouchers} 张凭证（DRAFT 状态）`)
      } else {
        error(`部分失败：成功 ${resp.created_vouchers} / 失败 ${resp.error_count}`)
      }
    } catch (e) {
      error((e as Error).message)
    } finally {
      setLoading(false)
    }
  }

  const reset = () => { setFile(null); setResult(null); if (fileRef.current) fileRef.current.value = '' }

  return (
    <div className="p-6 max-w-4xl">
      <div className="flex items-center gap-2 mb-2">
        <span className="bg-yellow-100 text-yellow-800 text-xs font-semibold px-2 py-0.5 rounded">DEV</span>
        <h1 className="text-xl font-bold text-slate-800">序时账导入</h1>
      </div>
      <p className="text-sm text-slate-400 mb-5">
        上传一家公司的序时账 Excel（凭证流水），按凭证号分组生成 DRAFT 凭证。
        所有凭证需进入"凭证管理"页面手工审核过账后才参与报表计算。
      </p>

      {/* Upload */}
      <div className="bg-white border border-slate-200 rounded-xl p-6 mb-5">
        <div className="text-xs text-slate-500 mb-3">
          <span className="font-semibold">Excel 格式要求：</span>
          <br />列：日期 | 凭证号 | 摘要 | 科目编码 | 科目名称 | 借方金额 | 贷方金额
          <br />同凭证号多行支持合并单元格；凭证号格式如 "记-1"；科目码可达 10 位（自动归一到 4 位母科目）
        </div>
        <div
          onClick={() => fileRef.current?.click()}
          className="border-2 border-dashed border-slate-300 hover:border-primary-400 rounded-xl p-8 text-center cursor-pointer transition-colors"
        >
          {file ? (
            <p className="text-primary-600 font-medium text-sm">{file.name} ({(file.size / 1024).toFixed(1)} KB)</p>
          ) : (
            <p className="text-slate-400 text-sm">点击选择 Excel 文件（.xlsx / .xls，上限 50MB）</p>
          )}
        </div>
        <input ref={fileRef} type="file" accept=".xlsx,.xls" className="hidden" onChange={handleSelect} />
        <div className="mt-4 flex gap-2">
          <button
            onClick={submit}
            disabled={!file || loading}
            className="px-5 py-2 bg-primary-600 hover:bg-primary-700 disabled:bg-slate-300 text-white text-sm rounded-lg font-medium"
          >
            {loading ? '导入中…' : '开始导入'}
          </button>
          {(file || result) && (
            <button onClick={reset} className="px-4 py-2 text-xs text-slate-500 hover:text-slate-700">
              重新选择
            </button>
          )}
        </div>
      </div>

      {/* Result */}
      {result && (
        <div className="space-y-4">
          {/* Summary cards */}
          <div className="grid grid-cols-4 gap-3">
            <div className="bg-white border border-slate-200 rounded-xl p-4 text-center">
              <p className="text-xs text-slate-400">总行数</p>
              <p className="text-2xl font-bold text-slate-700">{result.total_rows}</p>
            </div>
            <div className="bg-white border border-slate-200 rounded-xl p-4 text-center">
              <p className="text-xs text-slate-400">解析凭证</p>
              <p className="text-2xl font-bold text-primary-600">{result.parsed_vouchers}</p>
            </div>
            <div className="bg-green-50 border border-green-200 rounded-xl p-4 text-center">
              <p className="text-xs text-green-600">成功创建</p>
              <p className="text-2xl font-bold text-green-700">{result.created_vouchers}</p>
            </div>
            <div className={`border rounded-xl p-4 text-center ${result.error_count > 0 ? 'bg-red-50 border-red-200' : 'bg-slate-50 border-slate-200'}`}>
              <p className={`text-xs ${result.error_count > 0 ? 'text-red-600' : 'text-slate-400'}`}>失败</p>
              <p className={`text-2xl font-bold ${result.error_count > 0 ? 'text-red-700' : 'text-slate-700'}`}>{result.error_count}</p>
            </div>
          </div>

          {/* Column mapping debug */}
          <div className="bg-slate-50 border border-slate-200 rounded-lg px-4 py-2 text-xs text-slate-500 flex flex-wrap gap-3">
            <span className="font-semibold text-slate-700">列识别：</span>
            {Object.entries(result.column_mapping).map(([k, v]) => (
              <span key={k}><code className="text-primary-600">{k}</code> = {v}</span>
            ))}
          </div>

          {/* Errors */}
          {result.errors.length > 0 && (
            <div className="bg-white border border-red-200 rounded-xl overflow-hidden">
              <div className="px-4 py-2.5 bg-red-50 border-b border-red-100 text-sm font-semibold text-red-700">
                失败明细（{result.errors.length} 张凭证）
              </div>
              <div className="max-h-96 overflow-y-auto">
                {result.errors.map((e, i) => (
                  <div key={i} className="px-4 py-3 border-t border-slate-100">
                    <div className="flex items-baseline gap-2 text-sm">
                      <span className="font-mono font-semibold text-slate-700">{e.voucher_no}</span>
                      <span className="text-red-600 text-xs">{e.reason}</span>
                    </div>
                    {e.rows.length > 0 && (
                      <details className="mt-1">
                        <summary className="text-xs text-slate-400 cursor-pointer hover:text-slate-600">
                          展开前 {e.rows.length} 行原始数据
                        </summary>
                        <pre className="mt-1 text-xs text-slate-500 bg-slate-50 rounded p-2 overflow-x-auto">
                          {e.rows.map((r, ri) => `[${ri + 1}] ${JSON.stringify(r)}`).join('\n')}
                        </pre>
                      </details>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          {result.created_vouchers > 0 && (
            <div className="bg-blue-50 border border-blue-200 rounded-xl px-4 py-3 text-sm text-blue-800">
              💡 已创建的 {result.created_vouchers} 张凭证为 <b>DRAFT 状态</b>。
              请前往 <a href="/vouchers" className="underline font-medium">凭证管理</a> 页面审核过账后才会参与报表计算。
            </div>
          )}
        </div>
      )}
    </div>
  )
}
