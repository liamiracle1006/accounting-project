import { useState, useEffect } from 'react'
import { enterpriseApi, type EnterpriseProfile } from '@/api/enterprise'
import { useToast } from '@/hooks/useToast'
import { PageLoader } from '@/components/common/Spinner'

export default function SettingsPage() {
  const [profile, setProfile] = useState<EnterpriseProfile | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [companyName, setCompanyName] = useState('')
  const [industry, setIndustry] = useState('')
  const { success, error } = useToast()

  useEffect(() => {
    enterpriseApi.getProfile()
      .then(p => { setProfile(p); setCompanyName(p.company_name); setIndustry(p.industry) })
      .catch(() => { /* no profile yet */ })
      .finally(() => setLoading(false))
  }, [])

  const save = async () => {
    setSaving(true)
    try {
      if (profile) {
        await enterpriseApi.updateProfile(profile.profile_id, { company_name: companyName, industry })
      } else {
        const p = await enterpriseApi.createProfile({ company_name: companyName, industry })
        setProfile(p)
      }
      success('企业信息已保存')
    } catch (e) { error((e as Error).message) }
    finally { setSaving(false) }
  }

  if (loading) return <PageLoader />

  return (
    <div className="p-6 max-w-2xl">
      <h1 className="text-xl font-bold text-slate-800 mb-5">企业设置</h1>
      <div className="bg-white border border-slate-200 rounded-xl p-5 space-y-4">
        <div>
          <label className="text-xs font-medium text-slate-500 block mb-1">公司名称</label>
          <input value={companyName} onChange={e => setCompanyName(e.target.value)}
            className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500" />
        </div>
        <div>
          <label className="text-xs font-medium text-slate-500 block mb-1">行业</label>
          <input value={industry} onChange={e => setIndustry(e.target.value)}
            className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500" />
        </div>
        <button onClick={save} disabled={saving}
          className="px-4 py-2 bg-primary-600 hover:bg-primary-700 disabled:bg-slate-300 text-white text-sm rounded-lg font-medium">
          {saving ? '保存中…' : '保存'}
        </button>
      </div>
    </div>
  )
}
