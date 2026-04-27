import { api } from './client'
import type { SubjectNode } from '@/types'

export const subjectsApi = {
  tree: (): Promise<SubjectNode[]> =>
    api.get('/api/subjects/tree'),

  create: (data: Omit<SubjectNode, 'children'>): Promise<SubjectNode> =>
    api.post('/api/subjects', data),

  update: (code: string, data: Partial<SubjectNode>): Promise<SubjectNode> =>
    api.patch(`/api/subjects/${code}`, data),

  delete: (code: string): Promise<void> =>
    api.del(`/api/subjects/${code}`),

  toggle: (code: string, isEnabled: boolean): Promise<SubjectNode> =>
    api.patch(`/api/subjects/${code}`, { is_enabled: isEnabled }),
}
