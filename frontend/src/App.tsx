import { Suspense, lazy } from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { Layout } from '@/components/layout/Layout'
import { RequireAuth } from '@/router/index'
import { PageLoader } from '@/components/common/Spinner'

// Lazy-load all pages for code splitting
const LoginPage          = lazy(() => import('@/features/auth/LoginPage'))
const DashboardPage      = lazy(() => import('@/features/dashboard/DashboardPage'))
const WorkbenchPage      = lazy(() => import('@/features/workbench/WorkbenchPage'))
const RecordsPage        = lazy(() => import('@/features/records/RecordsPage'))
const VoucherWorkbench   = lazy(() => import('@/features/vouchers/VoucherWorkbenchPage'))
const AIVoucherPage      = lazy(() => import('@/features/ai-voucher/AIVoucherPage'))
const BatchImportConsole = lazy(() => import('@/features/batch-import/BatchImportConsole'))
const PeriodClosingPage  = lazy(() => import('@/features/periods/PeriodClosingPage'))
const ReportsPage        = lazy(() => import('@/features/reports/ReportsPage'))
const TrialBalancePage      = lazy(() => import('@/features/reports/TrialBalancePage'))
const DetailedLedgerPage    = lazy(() => import('@/features/reports/DetailedLedgerPage'))
const BalanceSheetPage      = lazy(() => import('@/features/reports/BalanceSheetPage'))
const IncomeStatementPage   = lazy(() => import('@/features/reports/IncomeStatementPage'))
const ValidatePage          = lazy(() => import('@/features/validate/ValidatePage'))
const ExpensesPage       = lazy(() => import('@/features/expenses/ExpensesPage'))
const DecisionsPage      = lazy(() => import('@/features/decisions/DecisionsPage'))
const AssetsPage         = lazy(() => import('@/features/assets/AssetsPage'))
const SubjectsPage       = lazy(() => import('@/features/subjects/SubjectsPage'))
const SetupWizardPage    = lazy(() => import('@/features/setup/SetupWizardPage'))
const SettingsPage       = lazy(() => import('@/features/settings/SettingsPage'))

export default function App() {
  return (
    <BrowserRouter>
      <Suspense fallback={<PageLoader />}>
        <Routes>
          <Route path="/login" element={<LoginPage />} />

          <Route element={<RequireAuth />}>
            <Route element={<Layout />}>
              <Route index element={<Navigate to="/dashboard" replace />} />
              <Route path="dashboard"  element={<DashboardPage />} />
              <Route path="workbench"  element={<WorkbenchPage />} />
              <Route path="records"    element={<RecordsPage />} />
              <Route path="vouchers"   element={<VoucherWorkbench />} />
              <Route path="ai-voucher" element={<AIVoucherPage />} />
              <Route path="batch"      element={<BatchImportConsole />} />
              <Route path="closing"    element={<PeriodClosingPage />} />
              <Route path="reports"        element={<ReportsPage />} />
              <Route path="trial-balance"    element={<TrialBalancePage />} />
              <Route path="ledger"           element={<DetailedLedgerPage />} />
              <Route path="balance-sheet"    element={<BalanceSheetPage />} />
              <Route path="income-statement" element={<IncomeStatementPage />} />
              <Route path="validate"         element={<ValidatePage />} />
              <Route path="expenses"   element={<ExpensesPage />} />
              <Route path="decisions"  element={<DecisionsPage />} />
              <Route path="assets"     element={<AssetsPage />} />
              <Route path="subjects"   element={<SubjectsPage />} />
              <Route path="setup"      element={<SetupWizardPage />} />
              <Route path="settings"   element={<SettingsPage />} />
            </Route>
          </Route>

          <Route path="*" element={<Navigate to="/dashboard" replace />} />
        </Routes>
      </Suspense>
    </BrowserRouter>
  )
}
