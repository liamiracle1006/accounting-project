import { api } from './client'

export interface EnterpriseProfile {
  profile_id: number
  company_name: string
  industry: string
  [key: string]: unknown
}

export const enterpriseApi = {
  getProfile: (): Promise<EnterpriseProfile> =>
    api.get('/api/enterprise/profile'),

  createProfile: (data: Partial<EnterpriseProfile>): Promise<EnterpriseProfile> =>
    api.post('/api/enterprise/profile', data),

  updateProfile: (id: number, data: Partial<EnterpriseProfile>): Promise<EnterpriseProfile> =>
    api.put(`/api/enterprise/profile/${id}`, data),

  thresholdRecommendation: () =>
    api.get('/api/enterprise/threshold-recommendation'),

  annualPlan: (year: number) =>
    api.get(`/api/enterprise/annual-plan/${year}`),

  generateAnnualPlan: (year: number) =>
    api.post(`/api/enterprise/annual-plan/${year}/generate`),
}
