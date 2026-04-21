import { NavLink } from 'react-router-dom'
import { useAuthStore, isFinance, isBoss } from '@/store/useAuthStore'

interface NavItem {
  to: string
  label: string
  financeOnly?: boolean
  bossOnly?: boolean
  deptOnly?: boolean
}

const navItems: NavItem[] = [
  { to: '/dashboard',    label: '仪表盘' },
  { to: '/workbench',   label: '财务工作台' },
  { to: '/records',     label: '流水记录' },
  { to: '/vouchers',    label: '凭证管理',   financeOnly: true },
  { to: '/ai-voucher',  label: 'AI 记账',    financeOnly: true },
  { to: '/batch',       label: '批量导入',   financeOnly: true },
  { to: '/closing',     label: '月末结账',   financeOnly: true },
  { to: '/reports',        label: '财务报表',   financeOnly: true },
  { to: '/trial-balance',  label: '科目余额表', financeOnly: true },
  { to: '/ledger',           label: '明细账',     financeOnly: true },
  { to: '/balance-sheet',    label: '资产负债表', financeOnly: true },
  { to: '/income-statement', label: '利润表',     financeOnly: true },
  { to: '/validate',         label: '[Dev] 报表验证', financeOnly: true },
  { to: '/expenses',    label: '费用申请' },
  { to: '/decisions',   label: '老板决策台', bossOnly: true },
  { to: '/assets',      label: '固定资产',   financeOnly: true },
  { to: '/subjects',    label: '科目管理',   financeOnly: true },
  { to: '/setup',       label: '建账向导',   financeOnly: true },
  { to: '/settings',    label: '企业设置',   financeOnly: true },
]

export function Sidebar() {
  const { user, logout } = useAuthStore()
  const finance = isFinance(user)
  const boss    = isBoss(user)
  const isDept  = user?.role === 'DEPT_MANAGER'

  const visible = navItems.filter(item => {
    if (isDept) return item.deptOnly || item.to === '/expenses'
    if (item.financeOnly && !finance) return false
    if (item.bossOnly && !boss) return false
    return true
  })

  return (
    <aside className="w-52 min-h-screen bg-sidebar-bg flex flex-col">
      <div className="px-4 py-5 border-b border-white/10">
        <span className="text-white font-bold text-lg tracking-wide">AgentLedger</span>
        <p className="text-sidebar-text text-xs mt-1 truncate">{user?.display_name}</p>
      </div>

      <nav className="flex-1 py-3 overflow-y-auto">
        {visible.map(item => (
          <NavLink
            key={item.to}
            to={item.to}
            className={({ isActive }) =>
              `block px-4 py-2 text-sm transition-colors ${
                isActive
                  ? 'bg-sidebar-active text-white font-medium'
                  : 'text-sidebar-text hover:bg-sidebar-hover hover:text-white'
              }`
            }
          >
            {item.label}
          </NavLink>
        ))}
      </nav>

      <div className="p-4 border-t border-white/10">
        <button
          onClick={logout}
          className="w-full text-left text-xs text-sidebar-text hover:text-white transition-colors"
        >退出登录</button>
      </div>
    </aside>
  )
}
