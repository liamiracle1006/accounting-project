import { useToastStore } from '@/store/useToastStore'

const typeStyles = {
  success: 'bg-green-600',
  error:   'bg-red-600',
  info:    'bg-primary-600',
}

export function ToastContainer() {
  const { toasts, dismiss } = useToastStore()
  return (
    <div className="fixed top-4 right-4 z-[9999] flex flex-col gap-2 pointer-events-none">
      {toasts.map(t => (
        <div
          key={t.id}
          onClick={() => dismiss(t.id)}
          className={`${typeStyles[t.type]} text-white px-4 py-2.5 rounded-lg shadow-lg text-sm
            pointer-events-auto cursor-pointer min-w-[220px] max-w-sm
            animate-[fadeIn_0.2s_ease]`}
        >
          {t.message}
        </div>
      ))}
    </div>
  )
}
