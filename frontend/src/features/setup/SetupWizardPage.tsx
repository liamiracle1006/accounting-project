import { useState, useEffect, useCallback } from 'react'
import { initialBalancesApi } from '@/api/initialBalances'
import { useToast } from '@/hooks/useToast'
import { PageLoader } from '@/components/common/Spinner'
import type { InitialBalanceNode } from '@/types'

const fmt = (n: number) => n.toLocaleString('zh-CN', { minimumFractionDigits: 2 })

function BalanceRow({ node, depth, onChange }: {
  node: InitialBalanceNode; depth: number;
  onChange: (code: string, field: 'opening_balance' | 'ytd_debit' | 'ytd_credit', val: number) => void
}) {
  const hasChildren = (node.children?.length ?? 0) > 0
  return (
    <>
      <tr className={`border-t border-slate-100 ${node.is_ai_sponge ? 'bg-orange-50' : ''}`}>
        <td className="px-3 py-2 font-mono text-xs" style={{ paddingLeft: `${12 + depth * 16}px` }}>
          {node.subject_code} {node.subject_name}
          {node.is_ai_sponge && <span className="ml-1 text-orange-500 text-xs">AI配平</span>}
        </td>
        <td className="px-2 py-1 text-xs text-center">{node.balance_direction === 'DEBIT' ? '借' : '贷'}</td>
        {(['opening_balance', 'ytd_debit', 'ytd_credit'] as const).map(field => (
          <td key={field} className="px-2 py-1">
            {hasChildren
              ? <span className="text-xs text-slate-400 block text-right pr-2">{fmt(node[field])}</span>
              : <input type="number" step="0.01" defaultValue={node[field]}
                  onBlur={e => onChange(node.subject_code, field, parseFloat(e.target.value) || 0)}
                  className="w-full border border-slate-200 rounded px-2 py-0.5 text-xs text-right focus:outline-none focus:ring-1 focus:ring-primary-500" />}
          </td>
        ))}
      </tr>
      {node.children?.map(c => (
        <BalanceRow key={c.subject_code} node={c} depth={depth + 1} onChange={onChange} />
      ))}
    </>
  )
}

export default function SetupWizardPage() {
  const [tree, setTree] = useState<InitialBalanceNode[]>([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [trial, setTrial] = useState<{ opening_balanced: boolean } | null>(null)
  const [edits, setEdits] = useState<Record<string, { opening_balance?: number; ytd_debit?: number; ytd_credit?: number }>>({})
  const { success, error } = useToast()

  const load = useCallback(async () => {
    try { setTree(await initialBalancesApi.withSubjects()) }
    catch (e) { error((e as Error).message) }
    finally { setLoading(false) }
  }, [error])

  const loadTrial = useCallback(async () => {
    try { setTrial(await initialBalancesApi.trialBalance()) }
    catch { /* optional */ }
  }, [])

  useEffect(() => { load(); loadTrial() }, [load, loadTrial])

  const handleChange = (code: string, field: 'opening_balance' | 'ytd_debit' | 'ytd_credit', val: number) => {
    setEdits(prev => ({ ...prev, [code]: { ...prev[code], [field]: val } }))
  }

  const saveAll = async () => {
    setSaving(true)
    const balances = Object.entries(edits).map(([subject_code, vals]) => ({ subject_code, ...vals }))
    try {
      await initialBalancesApi.batchSave(balances as Parameters<typeof initialBalancesApi.batchSave>[0])
      success('期初余额已保存')
      await loadTrial()
    } catch (e) { error((e as Error).message) }
    finally { setSaving(false) }
  }

  const complete = async () => {
    try {
      await initialBalancesApi.complete()
      success('建账完成！')
    } catch (e) { error((e as Error).message) }
  }

  if (loading) return <PageLoader />

  return (
    <div className="p-6 max-w-5xl">
      <h1 className="text-xl font-bold text-slate-800 mb-5">建账向导 — 期初余额</h1>
      <div className="flex gap-3 mb-4">
        <button onClick={() => initialBalancesApi.exportTemplate()} className="px-3 py-1.5 text-xs border border-slate-300 rounded-lg hover:bg-slate-50">下载 Excel 模板</button>
        <label className="px-3 py-1.5 text-xs border border-slate-300 rounded-lg hover:bg-slate-50 cursor-pointer">
          📥 导入 Excel
          <input type="file" accept=".xlsx,.xls,.csv" className="hidden" onChange={async e => {
            const f = e.target.files?.[0]; if (!f) return
            try { await initialBalancesApi.importExcel(f); success('导入成功'); load() }
            catch (err) { error((err as Error).message) }
          }} />
        </label>
      </div>

      {trial && (
        <div className={`mb-4 px-4 py-2.5 rounded-lg text-sm flex items-center gap-2 ${trial.opening_balanced ? 'bg-green-50 text-green-700' : 'bg-amber-50 text-amber-700'}`}>
          {trial.opening_balanced ? '✅ 期初余额借贷平衡' : '⚠️ 期初余额借贷不平衡'}
        </div>
      )}

      <div className="bg-white border border-slate-200 rounded-xl overflow-hidden mb-4">
        <table className="w-full text-xs">
          <thead className="bg-slate-50"><tr className="text-slate-500">
            <th className="px-3 py-2 text-left">科目</th>
            <th className="px-3 py-2 text-center">方向</th>
            <th className="px-3 py-2 text-right">期初余额</th>
            <th className="px-3 py-2 text-right">本年借方</th>
            <th className="px-3 py-2 text-right">本年贷方</th>
          </tr></thead>
          <tbody>
            {tree.map(n => <BalanceRow key={n.subject_code} node={n} depth={0} onChange={handleChange} />)}
          </tbody>
        </table>
      </div>

      <div className="flex gap-3">
        <button onClick={saveAll} disabled={saving} className="px-4 py-2 bg-primary-600 hover:bg-primary-700 disabled:bg-slate-300 text-white text-sm rounded-lg font-medium">
          {saving ? '保存中…' : '保存全部余额'}
        </button>
        <button onClick={complete} className="px-4 py-2 border border-slate-300 hover:bg-slate-50 text-sm rounded-lg">
          完成建账 →
        </button>
      </div>
    </div>
  )
}
