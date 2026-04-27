import { useToastStore } from '@/store/useToastStore'

export function useToast() {
  const show = useToastStore(s => s.show)
  return {
    toast: show,
    success: (msg: string) => show(msg, 'success'),
    error: (msg: string) => show(msg, 'error'),
    info: (msg: string) => show(msg, 'info'),
  }
}
