import { useEffect, useRef } from 'react'

export function usePoll(
  fn: () => Promise<boolean>, // returns true to stop polling
  intervalMs: number,
  active: boolean,
) {
  const fnRef = useRef(fn)
  fnRef.current = fn

  useEffect(() => {
    if (!active) return
    const id = setInterval(async () => {
      const stop = await fnRef.current().catch(() => false)
      if (stop) clearInterval(id)
    }, intervalMs)
    return () => clearInterval(id)
  }, [active, intervalMs])
}
