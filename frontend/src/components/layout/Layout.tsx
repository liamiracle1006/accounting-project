import { Outlet } from 'react-router-dom'
import { Sidebar } from './Sidebar'
import { ToastContainer } from '@/components/common/Toast'

export function Layout() {
  return (
    <div className="flex min-h-screen bg-slate-50">
      <Sidebar />
      <main className="flex-1 overflow-x-hidden">
        <Outlet />
      </main>
      <ToastContainer />
    </div>
  )
}
