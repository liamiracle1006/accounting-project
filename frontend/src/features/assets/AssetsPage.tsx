import { useState, useEffect } from 'react'
import { assetsApi } from '@/api/assets'
import { useToast } from '@/hooks/useToast'
import { PageLoader } from '@/components/common/Spinner'
import type { Asset } from '@/types'

const fmt = (n: number) => n.toLocaleString('zh-CN', { minimumFractionDigits: 2 })

export default function AssetsPage() {
  const [assets, setAssets] = useState<Asset[]>([])
  const [loading, setLoading] = useState(true)
  const { success, error } = useToast()
  const now = new Date()

  useEffect(() => {
    assetsApi.list().then(setAssets).catch(e => error((e as Error).message)).finally(() => setLoading(false))
  }, [])  // eslint-disable-line

  const runDepreciation = async () => {
    try {
      await assetsApi.runDepreciation(now.getFullYear(), now.getMonth() + 1)
      success('折旧计算完成')
    } catch (e) { error((e as Error).message) }
  }

  if (loading) return <PageLoader />

  return (
    <div className="p-6 max-w-4xl">
      <div className="flex items-center justify-between mb-5">
        <h1 className="text-xl font-bold text-slate-800">固定资产</h1>
        <button onClick={runDepreciation} className="px-3 py-1.5 border border-primary-400 text-primary-600 text-xs rounded-lg hover:bg-primary-50 font-medium">
          运行本月折旧
        </button>
      </div>
      <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
        <table className="w-full text-sm"><thead className="bg-slate-50"><tr className="text-xs text-slate-500">
          <th className="px-4 py-3 text-left">资产名称</th><th className="px-4 py-3 text-right">原值</th>
          <th className="px-4 py-3 text-right">账面净值</th><th className="px-4 py-3 text-center">状态</th><th className="px-4 py-3 text-left">购入日期</th>
        </tr></thead><tbody>
          {assets.length === 0 && <tr><td colSpan={5} className="px-4 py-10 text-center text-slate-400">暂无固定资产</td></tr>}
          {assets.map(a => (
            <tr key={a.asset_id} className="border-t border-slate-100">
              <td className="px-4 py-3 font-medium">{a.name}</td>
              <td className="px-4 py-3 text-right font-mono">¥{fmt(a.original_value)}</td>
              <td className="px-4 py-3 text-right font-mono">¥{fmt(a.net_book_value)}</td>
              <td className="px-4 py-3 text-center"><span className="text-xs text-slate-500">{a.status}</span></td>
              <td className="px-4 py-3 text-xs text-slate-400">{a.purchase_date}</td>
            </tr>
          ))}
        </tbody></table>
      </div>
    </div>
  )
}
