import { api } from './client'
import type { ImportSession, AbnormalSubject } from '@/types'

export const importsApi = {
  createSession: (source_system: string): Promise<ImportSession> =>
    api.post('/api/imports/sessions', { source_system }),

  exportGuide: (system: string): Promise<{ guide_html: string }> =>
    api.get(`/api/imports/export-guide/${system}`),

  uploadRawData: (sessionId: number, file: File) => {
    const form = new FormData()
    form.append('file', file)
    return api.post(`/api/imports/${sessionId}/upload-raw-data`, form)
  },

  mapSubjects: (sessionId: number) =>
    api.post(`/api/imports/${sessionId}/map-subjects`),

  abnormalSubjects: (sessionId: number): Promise<AbnormalSubject[]> =>
    api.get(`/api/imports/${sessionId}/abnormal-subjects`),

  confirmSubject: (sessionId: number, stagingId: number, mappedTo: string) =>
    api.post(`/api/imports/${sessionId}/confirm-subject/${stagingId}`, { mapped_to: mappedTo }),

  skipSubject: (sessionId: number, stagingId: number) =>
    api.post(`/api/imports/${sessionId}/skip-subject/${stagingId}`),

  executeImport: (sessionId: number) =>
    api.post(`/api/imports/${sessionId}/execute-import`),
}
