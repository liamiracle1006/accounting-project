import { api } from './client'
import type { TrialBalanceParams, TrialBalanceResponse, DetailedLedgerParams, DetailedLedgerResponse } from '@/types'

function buildQuery(params: Record<string, string | number | boolean | undefined>): string {
  const q = Object.entries(params)
    .filter(([, v]) => v !== undefined && v !== null && v !== '')
    .map(([k, v]) => `${k}=${encodeURIComponent(String(v))}`)
    .join('&')
  return q ? `?${q}` : ''
}

export const reportsApi = {
  // ── Sprint 4.1 科目余额表 ──────────────────────────────────────────
  trialBalance: (params: TrialBalanceParams = {}) =>
    api.get<TrialBalanceResponse>(
      `/api/reports/trial-balance${buildQuery(params as Record<string, string | number | boolean | undefined>)}`
    ),

  // ── Sprint 4.2 明细账 ─────────────────────────────────────────────
  detailedLedger: (params: DetailedLedgerParams) =>
    api.get<DetailedLedgerResponse>(
      `/api/reports/detailed-ledger${buildQuery(params as Record<string, string | number | boolean | undefined>)}`
    ),

  // ── 现有报表（保持不动）──────────────────────────────────────────
  balanceSheet: (asOf: string) =>
    api.get(`/api/reports/balance-sheet?as_of=${asOf}`),

  incomeStatement: (dateFrom: string, dateTo: string) =>
    api.get(`/api/reports/income-statement?date_from=${dateFrom}&date_to=${dateTo}`),

  cashFlow: (dateFrom: string, dateTo: string) =>
    api.get(`/api/reports/cash-flow?date_from=${dateFrom}&date_to=${dateTo}`),

  equityChanges: (year: number) =>
    api.get(`/api/reports/equity-changes?year=${year}`),
}
