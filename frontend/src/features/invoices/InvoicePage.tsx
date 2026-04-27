import { useState, useEffect, useCallback } from 'react'
import { api } from '@/api/client'
import { useToast } from '@/hooks/useToast'
import { PageLoader } from '@/components/common/Spinner'

interface Invoice {
  invoice_id: number
  invoice_type: 'INPUT' | 'OUTPUT'
  invoice_number: string
  invoice_date: string
  seller_name: string | null
  buyer_name: string | null
  subtotal_amount: number
  tax_rate: number | null
  tax_amount: number
  total_amount: number
  status: 'UNVERIFIED' | 'VERIFIED' | 'INVALID'
  source: string
  voucher_id: number | null
  items_summary: string | null
}

const fmt = (n: number) => n.toLocaleString('zh-CN', { minimumFractionDigits: 2 })

const STATUS_LABEL: Record<string, [string, string]> = {
  UNVERIFIED: ['未验证', 'text-amber-600 bg-amber-50'],
  VERIFIED:   ['已验证', 'text-green-600 bg-green-50'],
  INVALID:    ['已作废', 'text-red-600 bg-red-50'],
}

const BLANK_FORM = {
  invoice_type: 'INPUT' as 'INPUT' | 'OUTPUT',
  invoice_number: '',
  invoice_date: new Date().toISOString().slice(0, 10),
  seller_name: '',
  buyer_name: '',
  subtotal_amount: '',
  tax_rate: '',
  tax_amount: '',
  total_amount: '',
  items_summary: '',
}

export default function InvoicePage() {
  const [invoices, setInvoices] = useState<Invoice[]>([])
  const [loading, setLoading]   = useState(true)
  const [typeFilter,   setTypeFilter]   = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const [showForm, setShowForm] = useState(false)
  const [form, setForm]         = useState(BLANK_FORM)
  const [submitting, setSubmitting] = useState(false)
  const { success, error } = useToast()

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const params = new URLSearchParams()
      if (typeFilter)   params.set('invoice_type', typeFilter)
      if (statusFilter) params.set('status', statusFilter)
      const res = await api.get<Invoice[]>(`/api/invoices?${params}`)
      setInvoices(res)
    } catch (e) { error((e as Error).message) }
    finally { setLoading(false) }
  }, [typeFilter, statusFilter, error])

  useEffect(() => { load() }, [load])

  const verify = async (id: number) => {
    try {
      await api.put(`/api/invoices/${id}/verify`, {})
      success('发票已验证')
      load()
    } catch (e) { error((e as Error).message) }
  }

  const handleFormChange = (k: string, v: string) => setForm(f => ({ ...f, [k]: v }))

  const submitForm = async () => {
    if (!form.invoice_number.trim() || !form.invoice_date) {
      error('发票号和日期为必填'); return
    }
    setSubmitting(true)
    try {
      await api.post('/api/invoices', {
        ...form,
        subtotal_amount: Number(form.subtotal_amount) || 0,
        tax_rate:        form.tax_rate ? Number(form.tax_rate) : null,
        tax_amount:      Number(form.tax_amount) || 0,
        total_amount:    Number(form.total_amount) || 0,
      })
      success('发票已新增')
      setShowForm(false)
      setForm(BLANK_FORM)
      load()
    } catch (e) { error((e as Error).message) }
    finally { setSubmitting(false) }
  }

  if (loading) return <PageLoader />

  return (
    <div className="p-6 max-w-6xl">
      <div className="flex items-center justify-between mb-5">
        <h1 className="text-xl font-bold text-slate-800">发票管理</h1>
        <button
          onClick={() => setShowForm(v => !v)}
          className="px-3 py-1.5 bg-primary-600 hover:bg-primary-700 text-white text-xs rounded-lg font-medium"
        >
          {showForm ? '取消' : '+ 新增发票'}
        </button>
      </div>

      {/* Inline form */}
      {showForm && (
        <div className="bg-white border border-slate-200 rounded-xl p-5 mb-5">
          <h2 className="text-sm font-semibold text-slate-700 mb-4">新增发票</h2>
          <div className="grid grid-cols-3 gap-3 mb-3">
            <label className="flex flex-col gap-1">
              <span className="text-xs text-slate-500">发票类型</span>
              <select value={form.invoice_type} onChange={e => handleFormChange('invoice_type', e.target.value)}
                className="border border-slate-200 rounded-lg px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500">
                <option value="INPUT">进项（INPUT）</option>
                <option value="OUTPUT">销项（OUTPUT）</option>
              </select>
            </label>
            <label className="flex flex-col gap-1">
              <span className="text-xs text-slate-500">发票号码 *</span>
              <input value={form.invoice_number} onChange={e => handleFormChange('invoice_number', e.target.value)}
                className="border border-slate-200 rounded-lg px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500" />
            </label>
            <label className="flex flex-col gap-1">
              <span className="text-xs text-slate-500">开票日期 *</span>
              <input type="date" value={form.invoice_date} onChange={e => handleFormChange('invoice_date', e.target.value)}
                className="border border-slate-200 rounded-lg px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500" />
            </label>
            <label className="flex flex-col gap-1">
              <span className="text-xs text-slate-500">销方名称</span>
              <input value={form.seller_name} onChange={e => handleFormChange('seller_name', e.target.value)}
                className="border border-slate-200 rounded-lg px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500" />
            </label>
            <label className="flex flex-col gap-1">
              <span className="text-xs text-slate-500">购方名称</span>
              <input value={form.buyer_name} onChange={e => handleFormChange('buyer_name', e.target.value)}
                className="border border-slate-200 rounded-lg px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500" />
            </label>
            <label className="flex flex-col gap-1">
              <span className="text-xs text-slate-500">税率（如 0.13）</span>
              <input type="number" step="0.01" value={form.tax_rate} onChange={e => handleFormChange('tax_rate', e.target.value)}
                className="border border-slate-200 rounded-lg px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500" />
            </label>
            <label className="flex flex-col gap-1">
              <span className="text-xs text-slate-500">不含税金额</span>
              <input type="number" step="0.01" value={form.subtotal_amount} onChange={e => handleFormChange('subtotal_amount', e.target.value)}
                className="border border-slate-200 rounded-lg px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500" />
            </label>
            <label className="flex flex-col gap-1">
              <span className="text-xs text-slate-500">税额</span>
              <input type="number" step="0.01" value={form.tax_amount} onChange={e => handleFormChange('tax_amount', e.target.value)}
                className="border border-slate-200 rounded-lg px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500" />
            </label>
            <label className="flex flex-col gap-1">
              <span className="text-xs text-slate-500">价税合计</span>
              <input type="number" step="0.01" value={form.total_amount} onChange={e => handleFormChange('total_amount', e.target.value)}
                className="border border-slate-200 rounded-lg px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500" />
            </label>
          </div>
          <label className="flex flex-col gap-1 mb-4">
            <span className="text-xs text-slate-500">货物/服务描述</span>
            <input value={form.items_summary} onChange={e => handleFormChange('items_summary', e.target.value)}
              className="w-full border border-slate-200 rounded-lg px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500" />
          </label>
          <button onClick={submitForm} disabled={submitting}
            className="px-4 py-2 bg-primary-600 hover:bg-primary-700 disabled:bg-slate-300 text-white text-sm rounded-lg font-medium">
            {submitting ? '保存中…' : '保存'}
          </button>
        </div>
      )}

      {/* Filters */}
      <div className="flex items-center gap-3 mb-3">
        <select value={typeFilter} onChange={e => setTypeFilter(e.target.value)}
          className="border border-slate-200 rounded-lg px-2 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-primary-500">
          <option value="">全部类型</option>
          <option value="INPUT">进项</option>
          <option value="OUTPUT">销项</option>
        </select>
        <select value={statusFilter} onChange={e => setStatusFilter(e.target.value)}
          className="border border-slate-200 rounded-lg px-2 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-primary-500">
          <option value="">全部状态</option>
          <option value="UNVERIFIED">未验证</option>
          <option value="VERIFIED">已验证</option>
          <option value="INVALID">已作废</option>
        </select>
      </div>

      {/* Table */}
      <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-slate-50">
            <tr className="text-xs text-slate-500">
              <th className="px-4 py-3 text-left">日期</th>
              <th className="px-4 py-3 text-left">发票号</th>
              <th className="px-4 py-3 text-left">类型</th>
              <th className="px-4 py-3 text-left">对方名称</th>
              <th className="px-4 py-3 text-right">不含税金额</th>
              <th className="px-4 py-3 text-right">税额</th>
              <th className="px-4 py-3 text-right">价税合计</th>
              <th className="px-4 py-3 text-center">状态</th>
              <th className="px-4 py-3 text-center">操作</th>
            </tr>
          </thead>
          <tbody>
            {invoices.length === 0 && (
              <tr><td colSpan={9} className="px-4 py-10 text-center text-slate-400">暂无发票记录</td></tr>
            )}
            {invoices.map(inv => {
              const [statusText, statusStyle] = STATUS_LABEL[inv.status] ?? [inv.status, 'text-slate-600 bg-slate-100']
              const counterparty = inv.invoice_type === 'INPUT' ? inv.seller_name : inv.buyer_name
              return (
                <tr key={inv.invoice_id} className="border-t border-slate-100 hover:bg-slate-50">
                  <td className="px-4 py-2 text-xs">{inv.invoice_date}</td>
                  <td className="px-4 py-2 font-mono text-xs">{inv.invoice_number}</td>
                  <td className="px-4 py-2 text-xs">{inv.invoice_type === 'INPUT' ? '进项' : '销项'}</td>
                  <td className="px-4 py-2 text-xs text-slate-600">{counterparty ?? '—'}</td>
                  <td className="px-4 py-2 text-right font-mono text-xs">¥{fmt(inv.subtotal_amount)}</td>
                  <td className="px-4 py-2 text-right font-mono text-xs">¥{fmt(inv.tax_amount)}</td>
                  <td className="px-4 py-2 text-right font-mono text-xs font-medium">¥{fmt(inv.total_amount)}</td>
                  <td className="px-4 py-2 text-center">
                    <span className={`text-xs px-2 py-0.5 rounded font-medium ${statusStyle}`}>{statusText}</span>
                  </td>
                  <td className="px-4 py-2 text-center">
                    {inv.status === 'UNVERIFIED' && (
                      <button onClick={() => verify(inv.invoice_id)}
                        className="text-xs px-2 py-0.5 border border-green-400 text-green-600 rounded hover:bg-green-50">
                        验证
                      </button>
                    )}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}
