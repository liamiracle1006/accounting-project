import { api } from './client'

export interface OperationalRecord {
  record_id: number
  status: string
  voucher_id: number | null
  raw_text: string
  created_at: string
}

export const recordsApi = {
  list: (status?: string): Promise<OperationalRecord[]> => {
    const q = status ? `?status=${status}&limit=50` : '?limit=50'
    return api.get(`/api/records${q}`)
  },

  get: (id: number): Promise<OperationalRecord> =>
    api.get(`/api/records/${id}`),

  create: (raw_text: string): Promise<OperationalRecord> =>
    api.post('/api/records', { raw_text }),
}
