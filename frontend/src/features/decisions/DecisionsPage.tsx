import { useState, useEffect } from 'react'
import { api } from '@/api/client'
import { useToast } from '@/hooks/useToast'
import { PageLoader } from '@/components/common/Spinner'
import { Modal } from '@/components/common/Modal'

interface Decision { record_id: number; snapshot: string; choices: { choice_id: number; title: string; rationale: string }[] }

export default function DecisionsPage() {
  const [decisions, setDecisions] = useState<Decision[]>([])
  const [loading, setLoading] = useState(true)
  const [selected, setSelected] = useState<Decision | null>(null)
  const { success, error } = useToast()

  useEffect(() => {
    api.get<Decision[]>('/api/decisions?limit=50')
      .then(setDecisions).catch(e => error((e as Error).message)).finally(() => setLoading(false))
  }, [])  // eslint-disable-line

  const choose = async (decisionId: number, choiceId: number) => {
    try {
      await api.post(`/api/decisions/${decisionId}/choose`, { choice_id: choiceId })
      success('决策已提交')
      setSelected(null)
      setDecisions(prev => prev.filter(d => d.record_id !== decisionId))
    } catch (e) { error((e as Error).message) }
  }

  if (loading) return <PageLoader />

  return (
    <div className="p-6 max-w-3xl">
      <h1 className="text-xl font-bold text-slate-800 mb-5">老板决策台</h1>
      {decisions.length === 0 ? (
        <div className="text-center py-16 text-slate-400">暂无待决策事项 🎉</div>
      ) : (
        <div className="space-y-3">
          {decisions.map(d => (
            <div key={d.record_id} className="bg-white border border-slate-200 rounded-xl p-4 cursor-pointer hover:border-primary-300 transition-colors"
              onClick={() => setSelected(d)}>
              <p className="text-sm text-slate-700 line-clamp-2">{d.snapshot}</p>
              <p className="text-xs text-primary-600 mt-2">{d.choices.length} 个决策选项 →</p>
            </div>
          ))}
        </div>
      )}
      <Modal open={!!selected} onClose={() => setSelected(null)} title="待决策事项" width="max-w-lg">
        {selected && (
          <div>
            <p className="text-sm text-slate-700 mb-4 leading-relaxed">{selected.snapshot}</p>
            <div className="space-y-2">
              {selected.choices.map(c => (
                <button key={c.choice_id} onClick={() => choose(selected.record_id, c.choice_id)}
                  className="w-full text-left p-3 rounded-lg border border-slate-200 hover:border-primary-400 hover:bg-primary-50 transition-colors">
                  <p className="text-sm font-medium">{c.title}</p>
                  <p className="text-xs text-slate-500 mt-1">{c.rationale}</p>
                </button>
              ))}
            </div>
          </div>
        )}
      </Modal>
    </div>
  )
}
