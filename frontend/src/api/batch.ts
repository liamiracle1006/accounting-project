import { api } from './client'
import type {
  ParsePreviewResponse,
  ExecuteBatchInput,
  ExecuteBatchResponse,
  TaskProgressOut,
  BatchResultsOut,
} from '@/types'

export const batchApi = {
  parsePreview: (files: File[]): Promise<ParsePreviewResponse> => {
    const form = new FormData()
    files.forEach(f => form.append('files', f))
    return api.post('/api/batch/parse-preview', form)
  },

  execute: (data: ExecuteBatchInput): Promise<ExecuteBatchResponse> =>
    api.post('/api/batch/execute', data),

  progress: (taskId: number): Promise<TaskProgressOut> =>
    api.get(`/api/batch/task/${taskId}/progress`),

  results: (taskId: number): Promise<BatchResultsOut> =>
    api.get(`/api/batch/task/${taskId}/results`),
}
