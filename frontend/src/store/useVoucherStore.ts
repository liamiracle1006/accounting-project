import { create } from 'zustand'
import type { RecommendationItem, VoucherDraftOut } from '@/types'

interface VoucherState {
  // AI 双轨推荐
  recommendations: RecommendationItem[]
  selectedTrackIndex: number | null
  selectedHabitRuleId: number | null
  // Sprint 3.6 — 沉淀拦截快照
  aiOriginalLineCodes: string[]
  // 当前编辑草稿
  draft: VoucherDraftOut | null

  setRecommendations: (recs: RecommendationItem[]) => void
  selectTrack: (idx: number) => void
  setDraft: (draft: VoucherDraftOut | null) => void
  reset: () => void
}

const initialState = {
  recommendations: [] as RecommendationItem[],
  selectedTrackIndex: null as number | null,
  selectedHabitRuleId: null as number | null,
  aiOriginalLineCodes: [] as string[],
  draft: null as VoucherDraftOut | null,
}

export const useVoucherStore = create<VoucherState>()((set, get) => ({
  ...initialState,

  setRecommendations: (recommendations) =>
    set({ recommendations, selectedTrackIndex: null, selectedHabitRuleId: null, draft: null }),

  selectTrack: (idx) => {
    const rec = get().recommendations[idx]
    if (!rec) return
    set({
      selectedTrackIndex: idx,
      selectedHabitRuleId: rec.habit_rule_id ?? null,
      // 保存快照用于 Sprint 3.6 沉淀检测
      aiOriginalLineCodes: (rec.draft.lines ?? []).map(l => l.subject_code),
      draft: rec.draft,
    })
  },

  setDraft: (draft) => set({ draft }),

  reset: () => set(initialState),
}))
