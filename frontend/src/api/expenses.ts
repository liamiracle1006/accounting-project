import { api } from './client'
import type { ExpenseRequest } from '@/types'

export const expensesApi = {
  list: (status?: string): Promise<ExpenseRequest[]> => {
    const q = status ? `?status=${status}` : ''
    return api.get(`/api/expenses${q}`)
  },

  create: (data: { title: string; amount: number; expense_type: string; description: string }): Promise<ExpenseRequest> =>
    api.post('/api/expenses', data),

  approve: (id: number, note?: string) =>
    api.post(`/api/expenses/${id}/approve`, { note }),

  reject: (id: number, note?: string) =>
    api.post(`/api/expenses/${id}/reject`, { note }),
}
