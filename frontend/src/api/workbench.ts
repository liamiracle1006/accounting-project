import { api } from './client'
import type { WorkbenchVoucher } from '@/types'

export const workbenchApi = {
  list: (status?: string): Promise<WorkbenchVoucher[]> => {
    const q = status ? `?review_status=${status}` : ''
    return api.get(`/api/workbench/vouchers${q}`)
  },

  get: (id: number): Promise<WorkbenchVoucher> =>
    api.get(`/api/workbench/vouchers/${id}`),

  submit: (id: number): Promise<WorkbenchVoucher> =>
    api.post(`/api/workbench/vouchers/${id}/submit`),

  post: (id: number, note?: string): Promise<WorkbenchVoucher> =>
    api.post(`/api/workbench/vouchers/${id}/post`, { note }),

  reject: (id: number, note?: string): Promise<WorkbenchVoucher> =>
    api.post(`/api/workbench/vouchers/${id}/reject`, { note }),
}
