import { useEffect, useState } from 'react'

export function useReducedMotion(): boolean {
  const mq = window.matchMedia('(prefers-reduced-motion: reduce)')
  const [reduced, setReduced] = useState(mq.matches)
  useEffect(() => {
    const handler = (e: MediaQueryListEvent) => setReduced(e.matches)
    mq.addEventListener('change', handler)
    return () => mq.removeEventListener('change', handler)
  }, [])
  return reduced
}
