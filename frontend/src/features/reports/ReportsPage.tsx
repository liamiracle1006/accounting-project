import { Link } from 'react-router-dom'

const CARDS = [
  {
    to:    '/trial-balance',
    title: '科目余额表',
    desc:  '多级科目树 · 期初 / 本期 / 期末余额 · 支持导出 Excel',
  },
  {
    to:    '/ledger',
    title: '明细账',
    desc:  '逐行流水明细 · 运行余额 · 可追溯源凭证',
  },
  {
    to:    '/balance-sheet',
    title: '资产负债表',
    desc:  '企业准则 / 小企业准则 · 期末余额与年初余额',
  },
  {
    to:    '/income-statement',
    title: '利润表',
    desc:  '企业准则 / 小企业准则 · 本期与上期对比',
  },
]

export default function ReportsPage() {
  return (
    <div className="p-6 max-w-2xl">
      <h1 className="text-xl font-bold text-slate-800 mb-2">财务报表</h1>
      <p className="text-sm text-slate-400 mb-6">选择要查看的报表</p>
      <div className="grid grid-cols-2 gap-4">
        {CARDS.map(c => (
          <Link
            key={c.to}
            to={c.to}
            className="bg-white border border-slate-200 rounded-xl p-5 hover:border-primary-400 hover:shadow-sm transition-all group"
          >
            <p className="font-semibold text-slate-800 mb-1 group-hover:text-primary-700 transition-colors">
              {c.title}
            </p>
            <p className="text-xs text-slate-400">{c.desc}</p>
          </Link>
        ))}
      </div>
    </div>
  )
}
