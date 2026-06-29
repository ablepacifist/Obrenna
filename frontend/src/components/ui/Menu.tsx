import type { ReactNode } from 'react'
import { useEffect, useRef } from 'react'
import { cn } from '../../lib/cn'

export interface MenuItem {
  label: string
  icon?: ReactNode
  danger?: boolean
  onClick: () => void
}

interface MenuProps {
  items: MenuItem[]
  onClose: () => void
}

export function Menu({ items, onClose }: MenuProps) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const h = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) onClose()
    }
    document.addEventListener('mousedown', h)
    return () => document.removeEventListener('mousedown', h)
  }, [onClose])

  return (
    <div
      ref={ref}
      className="absolute right-0 top-8 z-40 min-w-[180px] rounded-lg border border-(--border) bg-(--surface) py-1 shadow-[0_1px_2px_rgba(28,25,22,.04),0_8px_24px_-8px_rgba(28,25,22,.10)]"
    >
      {items.map((it, i) => (
        <button
          key={i}
          onClick={it.onClick}
          className={cn(
            'w-full h-8 px-2.5 text-left text-[13px] inline-flex items-center gap-2 focus:outline-none focus-visible:bg-(--surface-2)',
            it.danger ? 'text-(--err) hover:bg-(--surface-2)' : 'text-(--ink) hover:bg-(--surface-2)',
          )}
        >
          {it.icon}
          <span>{it.label}</span>
        </button>
      ))}
    </div>
  )
}
