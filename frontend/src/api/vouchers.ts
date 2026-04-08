import { api } from './client'
import type {
  VoucherOut,
  DualTrackResponse,
  GenerateVoucherInput,
  ConfirmVoucherInput,
} from '@/types'

export const vouchersApi = {
  // AI 生成
  generate: (data: GenerateVoucherInput): Promise<DualTrackResponse> =>
    api.post('/api/voucher-ai/generate', data),

  confirm: (data: ConfirmVoucherInput): Promise<VoucherOut> =>
    api.post('/api/voucher-ai/confirm', data),

  // CRUD
  get: (id: number): Promise<VoucherOut> =>
    api.get(`/api/vouchers/${id}`),

  list: (params?: { review_status?: string; year?: number; month?: number }): Promise<VoucherOut[]> => {
    const q = new URLSearchParams()
    if (params?.review_status) q.set('review_status', params.review_status)
    if (params?.year)          q.set('year', String(params.year))
    if (params?.month)         q.set('month', String(params.month))
    return api.get(`/api/vouchers?${q}`)
  },

  create: (data: Omit<ConfirmVoucherInput, 'habit_rule_id'>): Promise<VoucherOut> =>
    api.post('/api/vouchers', data),

  update: (id: number, data: Partial<ConfirmVoucherInput>): Promise<VoucherOut> =>
    api.put(`/api/vouchers/${id}`, data),

  delete: (id: number): Promise<void> =>
    api.del(`/api/vouchers/${id}`),

  restore: (id: number): Promise<VoucherOut> =>
    api.post(`/api/vouchers/${id}/restore`),

  trash: (): Promise<VoucherOut[]> =>
    api.get('/api/vouchers/trash'),

  reorganize: (year: number, month: number): Promise<{ reorganized_count: number }> =>
    api.post('/api/vouchers/reorganize', { year, month }),
}
