import { useState, useEffect, useCallback } from 'react'
import { subjectsApi } from '@/api/subjects'
import { useToast } from '@/hooks/useToast'
import { Modal } from '@/components/common/Modal'
import { ConfirmDialog } from '@/components/common/ConfirmDialog'
import { PageLoader } from '@/components/common/Spinner'
import type { SubjectNode } from '@/types'

const categoryLabel: Record<string, string> = {
  ASSET: '资产', LIABILITY: '负债', EQUITY: '所有者权益', INCOME: '收入', EXPENSE: '费用',
}

function SubjectRow({ node, depth, onEdit, onToggle }: {
  node: SubjectNode; depth: number;
  onEdit: (n: SubjectNode) => void;
  onToggle: (n: SubjectNode) => void;
}) {
  return (
    <>
      <tr className="border-t border-slate-100 hover:bg-slate-50/50">
        <td className="px-4 py-2.5 font-mono text-sm" style={{ paddingLeft: `${16 + depth * 20}px` }}>
          {node.subject_code}
        </td>
        <td className="px-4 py-2.5 text-sm">{node.subject_name}</td>
        <td className="px-4 py-2.5 text-xs text-slate-500">{categoryLabel[node.category] ?? node.category}</td>
        <td className="px-4 py-2.5 text-xs text-center">{node.balance_direction === 'DEBIT' ? '借' : '贷'}</td>
        <td className="px-4 py-2.5 text-center">
          <span className={`text-xs font-medium ${node.is_enabled ? 'text-green-600' : 'text-slate-400'}`}>
            {node.is_enabled ? '启用' : '停用'}
          </span>
        </td>
        <td className="px-4 py-2.5 text-right whitespace-nowrap">
          <button onClick={() => onEdit(node)} className="text-xs text-primary-600 hover:underline mr-3">编辑</button>
          <button onClick={() => onToggle(node)} className="text-xs text-slate-500 hover:underline">
            {node.is_enabled ? '停用' : '启用'}
          </button>
        </td>
      </tr>
      {node.children?.map(c => (
        <SubjectRow key={c.subject_code} node={c} depth={depth + 1} onEdit={onEdit} onToggle={onToggle} />
      ))}
    </>
  )
}

export default function SubjectsPage() {
  const [tree, setTree] = useState<SubjectNode[]>([])
  const [loading, setLoading] = useState(true)
  const [modalOpen, setModalOpen] = useState(false)
  const [editing, setEditing] = useState<SubjectNode | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null)
  const { success, error } = useToast()

  const [code, setCode] = useState('')
  const [name, setName] = useState('')
  const [parentCode, setParentCode] = useState('')
  const [category, setCategory] = useState('ASSET')
  const [dir, setDir] = useState('DEBIT')

  const load = useCallback(async () => {
    try { setTree(await subjectsApi.tree()) }
    catch (e) { error((e as Error).message) }
    finally { setLoading(false) }
  }, [error])

  useEffect(() => { load() }, [load])

  const openModal = (node?: SubjectNode) => {
    setEditing(node ?? null)
    setCode(node?.subject_code ?? '')
    setName(node?.subject_name ?? '')
    setParentCode(node?.parent_code ?? '')
    setCategory(node?.category ?? 'ASSET')
    setDir(node?.balance_direction ?? 'DEBIT')
    setModalOpen(true)
  }

  const save = async () => {
    if (!code || !name) { error('请填写科目代码和名称'); return }
    try {
      if (editing) {
        await subjectsApi.update(editing.subject_code, { subject_name: name, category: category as SubjectNode['category'], balance_direction: dir as SubjectNode['balance_direction'] })
        success('科目已更新')
      } else {
        await subjectsApi.create({ subject_code: code, subject_name: name, category: category as SubjectNode['category'], balance_direction: dir as SubjectNode['balance_direction'], is_enabled: true, parent_code: parentCode || null })
        success('科目已新增')
      }
      setModalOpen(false); load()
    } catch (e) { error((e as Error).message) }
  }

  const toggle = async (node: SubjectNode) => {
    try { await subjectsApi.toggle(node.subject_code, !node.is_enabled); load() }
    catch (e) { error((e as Error).message) }
  }

  if (loading) return <PageLoader />

  return (
    <div className="p-6 max-w-4xl">
      <div className="flex items-center justify-between mb-5">
        <h1 className="text-xl font-bold text-slate-800">科目管理</h1>
        <button onClick={() => openModal()} className="px-3 py-1.5 bg-primary-600 text-white text-xs rounded-lg hover:bg-primary-700 font-medium">+ 新增科目</button>
      </div>
      <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-slate-50"><tr className="text-xs text-slate-500">
            <th className="px-4 py-3 text-left">科目代码</th>
            <th className="px-4 py-3 text-left">名称</th>
            <th className="px-4 py-3 text-left">类别</th>
            <th className="px-4 py-3 text-center">余额方向</th>
            <th className="px-4 py-3 text-center">状态</th>
            <th className="px-4 py-3"></th>
          </tr></thead>
          <tbody>
            {tree.map(n => <SubjectRow key={n.subject_code} node={n} depth={0} onEdit={openModal} onToggle={toggle} />)}
          </tbody>
        </table>
      </div>

      <Modal open={modalOpen} onClose={() => setModalOpen(false)} title={editing ? '编辑科目' : '新增科目'}
        footer={<>
          <button onClick={() => setModalOpen(false)} className="px-3 py-1.5 text-sm border border-slate-300 rounded-lg">取消</button>
          <button onClick={save} className="px-3 py-1.5 text-sm bg-primary-600 text-white rounded-lg hover:bg-primary-700">保存</button>
        </>}>
        <div className="space-y-3">
          {!editing && (
            <div>
              <label className="text-xs text-slate-500 block mb-1">科目代码 *</label>
              <input value={code} onChange={e => setCode(e.target.value)}
                className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500" />
            </div>
          )}
          <div>
            <label className="text-xs text-slate-500 block mb-1">科目名称 *</label>
            <input value={name} onChange={e => setName(e.target.value)}
              className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500" />
          </div>
          {!editing && (
            <div>
              <label className="text-xs text-slate-500 block mb-1">父科目代码（可选）</label>
              <input value={parentCode} onChange={e => setParentCode(e.target.value)}
                className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500" />
            </div>
          )}
          <div className="flex gap-3">
            <div className="flex-1">
              <label className="text-xs text-slate-500 block mb-1">类别</label>
              <select value={category} onChange={e => setCategory(e.target.value)}
                className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500">
                {Object.entries(categoryLabel).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
              </select>
            </div>
            <div className="w-28">
              <label className="text-xs text-slate-500 block mb-1">余额方向</label>
              <select value={dir} onChange={e => setDir(e.target.value)}
                className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500">
                <option value="DEBIT">借</option>
                <option value="CREDIT">贷</option>
              </select>
            </div>
          </div>
        </div>
      </Modal>

      <ConfirmDialog open={deleteTarget !== null} title="删除科目" message="确认删除此科目？" danger
        onConfirm={async () => {
          if (!deleteTarget) return
          try { await subjectsApi.delete(deleteTarget); success('科目已删除'); setDeleteTarget(null); load() }
          catch (e) { error((e as Error).message) }
        }}
        onCancel={() => setDeleteTarget(null)} />
    </div>
  )
}
