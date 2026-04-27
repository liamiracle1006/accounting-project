import { api } from './client'
import type { Asset } from '@/types'

export const assetsApi = {
  list: (status?: string): Promise<Asset[]> => {
    const q = status ? `?status=${status}` : ''
    return api.get(`/api/assets${q}`)
  },

  runDepreciation: (year: number, month: number) =>
    api.post('/api/assets/depreciation/run', { year, month }),
}
