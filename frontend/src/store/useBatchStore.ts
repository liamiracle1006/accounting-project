import { create } from 'zustand'
import type { StandardReceiptItem, TaskProgressOut, BatchResultsOut, ParseEngine } from '@/types'

interface BatchState {
  // 步骤 1-2
  files: File[]
  previewItems: StandardReceiptItem[]
  parseEngine: ParseEngine | null
  // 步骤 3
  taskId: number | null
  progress: TaskProgressOut | null
  // 步骤 4
  results: BatchResultsOut | null

  setFiles: (files: File[]) => void
  setPreview: (items: StandardReceiptItem[], engine: ParseEngine) => void
  setTaskId: (id: number) => void
  setProgress: (p: TaskProgressOut) => void
  setResults: (r: BatchResultsOut) => void
  reset: () => void
}

const initialState = {
  files: [] as File[],
  previewItems: [] as StandardReceiptItem[],
  parseEngine: null as ParseEngine | null,
  taskId: null as number | null,
  progress: null as TaskProgressOut | null,
  results: null as BatchResultsOut | null,
}

export const useBatchStore = create<BatchState>()((set) => ({
  ...initialState,
  setFiles: (files) => set({ files }),
  setPreview: (previewItems, parseEngine) => set({ previewItems, parseEngine }),
  setTaskId: (taskId) => set({ taskId }),
  setProgress: (progress) => set({ progress }),
  setResults: (results) => set({ results }),
  reset: () => set(initialState),
}))
