interface SettleDialogProps {
  open: boolean
  onKeepRule: () => void
  onIgnore: () => void
}

export function SettleDialog({ open, onKeepRule, onIgnore }: SettleDialogProps) {
  if (!open) return null
  return (
    <div className="fixed inset-0 bg-black/45 z-[1100] flex items-center justify-center p-4">
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-md overflow-hidden">
        <div className="px-6 pt-6 pb-4 border-b border-slate-200">
          <h3 className="text-base font-bold text-slate-800">✨ 更新 AI 习惯规则？</h3>
        </div>
        <p className="px-6 py-4 text-sm text-slate-500 leading-relaxed">
          检测到您修改了 AI 推荐的科目组合。<br />
          是否将此次修改沉淀为专属 AI 规则，让系统越用越智能？
        </p>
        <div className="px-6 pb-6 flex gap-3 justify-end">
          <button
            onClick={onIgnore}
            className="px-4 py-2 text-sm border border-slate-300 rounded-lg hover:bg-slate-50 text-slate-700"
          >仅修改本次</button>
          <button
            onClick={onKeepRule}
            className="px-4 py-2 text-sm bg-primary-600 hover:bg-primary-700 text-white rounded-lg"
          >是的，更新规则并保存</button>
        </div>
      </div>
    </div>
  )
}
