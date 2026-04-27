import { api } from './client'
import type { InitialBalanceNode, TrialBalanceResult } from '@/types'

export const initialBalancesApi = {
  withSubjects: (): Promise<InitialBalanceNode[]> =>
    api.get('/api/initial-balances/with-subjects'),

  batchSave: (balances: { subject_code: string; opening_balance: number; ytd_debit: number; ytd_credit: number }[]) =>
    api.post('/api/initial-balances/batch-save', { balances }),

  trialBalance: (): Promise<TrialBalanceResult> =>
    api.get('/api/initial-balances/trial-balance'),

  importExcel: (file: File) => {
    const form = new FormData()
    form.append('file', file)
    return api.post('/api/initial-balances/import', form)
  },

  complete: () =>
    api.post('/api/initial-balances/complete'),

  exportTemplate: () => {
    window.open('/api/initial-balances/export-template')
  },
}
