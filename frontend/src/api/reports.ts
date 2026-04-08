import { api } from './client'

export const reportsApi = {
  trialBalance: (dateFrom: string, dateTo: string) =>
    api.get(`/api/reports/trial-balance?date_from=${dateFrom}&date_to=${dateTo}`),

  incomeExpense: (year: number, month: number) =>
    api.get(`/api/reports/income-expense?year=${year}&month=${month}`),

  balanceSheet: (asOf: string) =>
    api.get(`/api/reports/balance-sheet?as_of=${asOf}`),

  incomeStatement: (dateFrom: string, dateTo: string) =>
    api.get(`/api/reports/income-statement?date_from=${dateFrom}&date_to=${dateTo}`),

  cashFlow: (dateFrom: string, dateTo: string) =>
    api.get(`/api/reports/cash-flow?date_from=${dateFrom}&date_to=${dateTo}`),

  equityChanges: (year: number) =>
    api.get(`/api/reports/equity-changes?year=${year}`),
}
