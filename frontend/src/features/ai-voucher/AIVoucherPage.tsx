import { useState } from 'react'
import { vouchersApi } from '@/api/vouchers'
import { useVoucherStore } from '@/store/useVoucherStore'
import { useToast } from '@/hooks/useToast'
import { DualTrackPanel } from './DualTrackPanel'
import { VoucherEditor } from './VoucherEditor'
import { HabitRuleDashboard } from '../habit-rules/HabitRuleDashboard'

type Tab = 'generate' | 'habits'

function todayStr() {
  return new Date().toISOString().slice(0, 10)
}

export default function AIVoucherPage() {
  const [tab, setTab] = useState<Tab>('generate')
  const [description, setDescription] = useState('')
  const [voucherDate, setVoucherDate] = useState(todayStr)
  const [voucherWord, setVoucherWord] = useState('记')
  const [generating, setGenerating] = useState(false)
  const { recommendations, setRecommendations, reset } = useVoucherStore()
  const { error } = useToast()

  const generate = async () => {
    if (!description.trim()) { error('请填写业务描述'); return }
    setGenerating(true)
    reset()
    try {
      const data = await vouchersApi.generate({ description, voucher_date: voucherDate })
      setRecommendations(data.recommendations)
    } catch (e) {
      error((e as Error).message)
    } finally {
      setGenerating(false)
    }
  }

  const handleSuccess = () => {
    setDescription('')
    reset()
  }

  return (
    <div className="p-6 max-w-4xl">
      <h1 className="text-xl font-bold text-slate-800 mb-5">AI 记账</h1>

      {/* Tabs */}
      <div className="flex gap-1 border-b border-slate-200 mb-6">
        {([['generate', 'AI 生成凭证'], ['habits', '业务习惯规则']] as [Tab, string][]).map(([key, label]) => (
          <button
            key={key}
            onClick={() => setTab(key)}
            className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
              tab === key
                ? 'border-primary-600 text-primary-700'
                : 'border-transparent text-slate-500 hover:text-slate-700'
            }`}
          >{label}</button>
        ))}
      </div>

      {/* Tab: AI 生成 */}
      {tab === 'generate' && (
        <div className="space-y-5">
          {/* 输入区 */}
          <div className="bg-white border border-slate-200 rounded-xl p-5">
            <div className="mb-3">
              <label className="text-xs font-medium text-slate-500 block mb-1">业务描述 *</label>
              <textarea
                value={description}
                onChange={e => setDescription(e.target.value)}
                rows={3}
                placeholder="例：支付阿里云服务器年费 12000 元"
                className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500 resize-none"
              />
            </div>
            <div className="flex gap-3">
              <div className="flex-1">
                <label className="text-xs font-medium text-slate-500 block mb-1">凭证日期</label>
                <input type="date" value={voucherDate} onChange={e => setVoucherDate(e.target.value)}
                  className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500" />
              </div>
              <div className="w-28">
                <label className="text-xs font-medium text-slate-500 block mb-1">凭证字</label>
                <select value={voucherWord} onChange={e => setVoucherWord(e.target.value)}
                  className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500">
                  {['记', '收', '付', '转'].map(w => <option key={w}>{w}</option>)}
                </select>
              </div>
              <div className="flex items-end">
                <button
                  onClick={generate}
                  disabled={generating}
                  className="px-5 py-2 bg-primary-600 hover:bg-primary-700 disabled:bg-slate-300 text-white text-sm rounded-lg font-medium"
                >
                  {generating ? 'AI 生成中…' : '🤖 AI 生成'}
                </button>
              </div>
            </div>
          </div>

          {/* 双轨推荐 */}
          {recommendations.length > 0 && (
            <div>
              <h3 className="text-sm font-semibold text-slate-600 mb-2">选择推荐方案</h3>
              <DualTrackPanel recommendations={recommendations} />
            </div>
          )}

          {/* 草稿编辑器 */}
          <VoucherEditor
            description={description}
            voucherDate={voucherDate}
            voucherWord={voucherWord}
            onSuccess={handleSuccess}
          />
        </div>
      )}

      {/* Tab: 习惯规则 */}
      {tab === 'habits' && <HabitRuleDashboard />}
    </div>
  )
}
