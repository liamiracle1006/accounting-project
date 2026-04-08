import { api } from './client'
import type { AccountingPeriod, CloseResult, TransferPnLResult } from '@/types'

export const periodsApi = {
  list: (): Promise<AccountingPeriod[]> =>
    api.get('/api/period'),

  close: (year: number, month: number): Promise<CloseResult> =>
    api.post(`/api/period/${year}/${month}/close`),

  transferPnL: (year: number, month: number): Promise<TransferPnLResult> =>
    api.post(`/api/period/${year}/${month}/transfer-pnl`),

  unclose: (year: number, month: number): Promise<{ message: string }> =>
    api.post(`/api/period/${year}/${month}/unclose`),
}
