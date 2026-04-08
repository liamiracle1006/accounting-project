import { useState, useEffect, useCallback } from 'react'
import { habitRulesApi } from '@/api/habitRules'
import { useToast } from '@/hooks/useToast'
import { Modal } from '@/components/common/Modal'
import { ConfirmDialog } from '@/components/common/ConfirmDialog'
import { PageLoader } from '@/components/common/Spinner'
import type { HabitRule } from '@/types'

const fmt = (n: number) => n.toLocaleString()

function maxWeight(rule: HabitRule): number {
  const edges = (rule.rule_json?.edges as { weight?: number }[] | undefined) ?? []
  return edges.length ? Math.max(...edges.map(e => e.weight ?? 1)) : 1
}

export function HabitRuleDashboard() {
  const [rules, setRules] = useState<HabitRule[]>([])
  const [loading, setLoading] = useState(true)
  const [editingRule, setEditingRule] = useState<HabitRule | null>(null)
  const [modalOpen, setModalOpen] = useState(false)
  const [deleteTarget, setDeleteTarget] = useState<number | null>(null)
  const { success, error } = useToast()

  // Form state
  const [name, setName] = useState('')
  const [desc, setDesc] = useState('')
  const [keywords, setKeywords] = useState('')
  const [jsonStr, setJsonStr] = useState('{"nodes":[],"edges":[]}')
  const [active, setActive] = useState(true)

  const load = useCallback(async () => {
    try {
      setRules(await habitRulesApi.list())
    } catch (e) {
      error((e as Error).message)
    } finally {
      setLoading(false)
    }
  }, [error])

  useEffect(() => { load() }, [load])

  const openModal = (rule?: HabitRule) => {
    setEditingRule(rule ?? null)
    setName(rule?.rule_name ?? '')
    setDesc(rule?.description ?? '')
    setKeywords((rule?.keywords ?? []).join(', '))
    setJsonStr(rule ? JSON.stringify(rule.rule_json, null, 2) : '{"nodes":[],"edges":[]}')
    setActive(rule?.is_active ?? true)
    setModalOpen(true)
  }

  const save = async () => {
    if (!name.trim()) { error('请填写规则名称'); return }
    const kw = keywords.split(',').map(s => s.trim()).filter(Boolean)
    if (!kw.length) { error('请至少填写一个关键词'); return }
    let rule_json: Record<string, unknown>
    try { rule_json = JSON.parse(jsonStr) } catch { error('DAG JSON 格式不正确'); return }
    const body = { rule_name: name.trim(), description: desc.trim() || null, keywords: kw, rule_json, is_active: active }
    try {
      if (editingRule) {
        await habitRulesApi.update(editingRule.id, body)
        success('规则已更新')
      } else {
        await habitRulesApi.create(body)
        success('规则已保存')
      }
      setModalOpen(false)
      load()
    } catch (e) {
      error((e as Error).message)
    }
  }

  const toggle = async (rule: HabitRule) => {
    try {
      await habitRulesApi.update(rule.id, { is_active: !rule.is_active })
      load()
    } catch (e) { error((e as Error).message) }
  }

  const doDelete = async () => {
    if (!deleteTarget) return
    try {
      await habitRulesApi.delete(deleteTarget)
      success('规则已删除')
      setDeleteTarget(null)
      load()
    } catch (e) { error((e as Error).message) }
  }

  if (loading) return <PageLoader />

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-sm font-semibold text-slate-600">业务习惯规则 ({rules.length})</h2>
        <button
          onClick={() => openModal()}
          className="px-3 py-1.5 bg-primary-600 hover:bg-primary-700 text-white text-xs rounded-lg font-medium"
        >+ 新增规则</button>
      </div>

      {rules.length === 0 ? (
        <div className="text-center py-12 text-slate-400 text-sm">暂无习惯规则，点击右上角新增</div>
      ) : (
        <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-slate-50">
              <tr className="text-xs text-slate-500">
                <th className="px-4 py-3 text-left">规则名称</th>
                <th className="px-4 py-3 text-left">关键词</th>
                <th className="px-4 py-3 text-center">权重</th>
                <th className="px-4 py-3 text-center">状态</th>
                <th className="px-4 py-3 text-left">创建时间</th>
                <th className="px-4 py-3"></th>
              </tr>
            </thead>
            <tbody>
              {rules.map(rule => {
                const w = maxWeight(rule)
                return (
                  <tr key={rule.id} className="border-t border-slate-100 hover:bg-slate-50/50">
                    <td className="px-4 py-3 font-medium">{rule.rule_name}</td>
                    <td className="px-4 py-3">
                      <div className="flex flex-wrap gap-1">
                        {rule.keywords.map(k => (
                          <span key={k} className="bg-blue-50 text-blue-700 text-xs px-2 py-0.5 rounded">{k}</span>
                        ))}
                      </div>
                    </td>
                    <td className="px-4 py-3 text-center text-xs">
                      <span className={w >= 5 ? 'text-amber-600 font-bold' : 'text-slate-400'}>
                        {w >= 5 ? `🔥 ${fmt(w)}` : fmt(w)}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-center">
                      <span className={`text-xs font-semibold ${rule.is_active ? 'text-green-600' : 'text-slate-400'}`}>
                        {rule.is_active ? '启用' : '停用'}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-xs text-slate-400">{rule.created_at.slice(0, 10)}</td>
                    <td className="px-4 py-3 text-right whitespace-nowrap">
                      <button onClick={() => openModal(rule)} className="text-xs text-primary-600 hover:underline mr-3">编辑</button>
                      <button onClick={() => toggle(rule)} className="text-xs text-slate-500 hover:underline mr-3">{rule.is_active ? '停用' : '启用'}</button>
                      <button onClick={() => setDeleteTarget(rule.id)} className="text-xs text-red-500 hover:underline">删除</button>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* 新增/编辑 Modal */}
      <Modal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        title={editingRule ? '编辑业务习惯规则' : '新增业务习惯规则'}
        footer={
          <>
            <button onClick={() => setModalOpen(false)} className="px-3 py-1.5 text-sm border border-slate-300 rounded-lg hover:bg-slate-50">取消</button>
            <button onClick={save} className="px-3 py-1.5 text-sm bg-primary-600 text-white rounded-lg hover:bg-primary-700">保存</button>
          </>
        }
      >
        <div className="space-y-3">
          <div>
            <label className="text-xs font-medium text-slate-500 block mb-1">规则名称 *</label>
            <input value={name} onChange={e => setName(e.target.value)} maxLength={100}
              placeholder="如：阿里云服务器年费摊销"
              className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500" />
          </div>
          <div>
            <label className="text-xs font-medium text-slate-500 block mb-1">描述（可选）</label>
            <input value={desc} onChange={e => setDesc(e.target.value)} maxLength={500}
              className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500" />
          </div>
          <div>
            <label className="text-xs font-medium text-slate-500 block mb-1">触发关键词 *（逗号分隔）</label>
            <input value={keywords} onChange={e => setKeywords(e.target.value)}
              placeholder="阿里云,服务器,云服务"
              className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500" />
          </div>
          <div>
            <label className="text-xs font-medium text-slate-500 block mb-1">DAG 规则 JSON *</label>
            <textarea value={jsonStr} onChange={e => setJsonStr(e.target.value)} rows={5}
              className="w-full border border-slate-200 rounded-lg px-3 py-2 text-xs font-mono focus:outline-none focus:ring-2 focus:ring-primary-500 resize-none" />
          </div>
          <label className="flex items-center gap-2 text-sm cursor-pointer select-none">
            <input type="checkbox" checked={active} onChange={e => setActive(e.target.checked)} className="w-4 h-4 accent-primary-600" />
            启用此规则
          </label>
        </div>
      </Modal>

      <ConfirmDialog
        open={deleteTarget !== null}
        title="删除习惯规则"
        message="确定删除这条习惯规则吗？删除后 AI 将遗忘该习惯。"
        confirmLabel="删除"
        danger
        onConfirm={doDelete}
        onCancel={() => setDeleteTarget(null)}
      />
    </div>
  )
}
