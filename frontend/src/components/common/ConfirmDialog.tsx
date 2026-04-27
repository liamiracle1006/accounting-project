interface ConfirmDialogProps {
  open: boolean
  title: string
  message: string
  confirmLabel?: string
  cancelLabel?: string
  danger?: boolean
  onConfirm: () => void
  onCancel: () => void
}

export function ConfirmDialog({
  open, title, message,
  confirmLabel = '确认', cancelLabel = '取消',
  danger = false, onConfirm, onCancel,
}: ConfirmDialogProps) {
  if (!open) return null
  return (
    <div className="fixed inset-0 bg-black/50 z-[1100] flex items-center justify-center p-4">
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-sm">
        <div className="p-5">
          <h3 className="font-semibold text-slate-800 mb-2">{title}</h3>
          <p className="text-sm text-slate-600">{message}</p>
        </div>
        <div className="px-5 pb-5 flex gap-2 justify-end">
          <button
            onClick={onCancel}
            className="px-3 py-1.5 text-sm border border-slate-300 rounded-lg hover:bg-slate-50"
          >{cancelLabel}</button>
          <button
            onClick={onConfirm}
            className={`px-3 py-1.5 text-sm rounded-lg text-white ${danger ? 'bg-red-600 hover:bg-red-700' : 'bg-primary-600 hover:bg-primary-700'}`}
          >{confirmLabel}</button>
        </div>
      </div>
    </div>
  )
}
