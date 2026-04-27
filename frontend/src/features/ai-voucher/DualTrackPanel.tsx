import type { RecommendationItem } from '@/types'
import { ConfidenceBadge } from '@/components/common/Badge'
import { useVoucherStore } from '@/store/useVoucherStore'

const sourceLabel: Record<string, string> = {
  HABIT:   '历史习惯',
  AI_RULE: 'AI 准则',
}

interface Props {
  recommendations: RecommendationItem[]
}

export function DualTrackPanel({ recommendations }: Props) {
  const { selectedTrackIndex, selectTrack } = useVoucherStore()

  return (
    <div className="flex gap-3 flex-wrap">
      {recommendations.map((rec, idx) => (
        <button
          key={idx}
          onClick={() => selectTrack(idx)}
          className={`flex-1 min-w-[220px] text-left p-4 rounded-xl border-2 transition-all
            ${selectedTrackIndex === idx
              ? 'border-primary-600 bg-primary-50 shadow-md'
              : 'border-slate-200 bg-white hover:border-primary-300'}`}
        >
          <div className="flex items-center gap-2 mb-2">
            <span className={`text-xs font-bold px-2 py-0.5 rounded-full
              ${rec.track === 'A' ? 'bg-indigo-100 text-indigo-700' : 'bg-slate-100 text-slate-600'}`}>
              Track {rec.track}
            </span>
            <span className="text-xs text-slate-500">{sourceLabel[rec.source]}</span>
            <ConfidenceBadge level={rec.confidence} />
          </div>
          <p className="text-sm text-slate-700 line-clamp-2">{rec.draft.memo || '（无摘要）'}</p>
          <div className="mt-2 text-xs text-slate-500">
            借方 ¥{rec.draft.total_debit.toLocaleString('zh-CN', { minimumFractionDigits: 2 })}
            {' · '}
            {rec.draft.lines.length} 行
          </div>
        </button>
      ))}
    </div>
  )
}
