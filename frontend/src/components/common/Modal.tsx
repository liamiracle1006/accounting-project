import { ReactNode, useEffect } from 'react'

interface ModalProps {
  open: boolean
  onClose: () => void
  title: string
  children: ReactNode
  footer?: ReactNode
  width?: string
}

export function Modal({ open, onClose, title, children, footer, width = 'max-w-lg' }: ModalProps) {
  useEffect(() => {
    if (!open) return
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [open, onClose])

  if (!open) return null

  return (
    <div
      className="fixed inset-0 bg-black/50 z-[1000] flex items-center justify-center p-4"
      onClick={e => { if (e.target === e.currentTarget) onClose() }}
    >
      <div className={`bg-white rounded-xl shadow-2xl w-full ${width} max-h-[85vh] flex flex-col`}>
        <div className="flex items-center px-5 py-4 border-b border-slate-200">
          <h3 className="font-semibold text-slate-800">{title}</h3>
          <button
            onClick={onClose}
            className="ml-auto text-slate-400 hover:text-slate-600 text-xl leading-none"
          >×</button>
        </div>
        <div className="flex-1 overflow-y-auto px-5 py-4">{children}</div>
        {footer && (
          <div className="px-5 py-3 border-t border-slate-200 flex justify-end gap-2">
            {footer}
          </div>
        )}
      </div>
    </div>
  )
}
