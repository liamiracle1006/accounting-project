import { api } from './client'
import type { HabitRule, HabitRuleCreateInput, HabitRuleUpdateInput } from '@/types'

export const habitRulesApi = {
  list: (): Promise<HabitRule[]> =>
    api.get('/api/voucher-ai/habit-rules'),

  create: (data: HabitRuleCreateInput): Promise<HabitRule> =>
    api.post('/api/voucher-ai/habit-rules', data),

  update: (id: number, data: HabitRuleUpdateInput): Promise<HabitRule> =>
    api.put(`/api/voucher-ai/habit-rules/${id}`, data),

  delete: (id: number): Promise<void> =>
    api.del(`/api/voucher-ai/habit-rules/${id}`),
}
