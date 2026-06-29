import type { ButtonHTMLAttributes } from 'react'
import { cn } from '../../lib/cn'

interface IconButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {}

export function IconButton({ className, ...p }: IconButtonProps) {
  return (
    <button
      {...p}
      className={cn(
        'inline-flex items-center justify-center w-8 h-8 rounded-md',
        'text-(--ink-muted) hover:text-(--ink) hover:bg-(--surface-2)',
        'focus:outline-none focus-visible:ring-2 focus-visible:ring-(--accent) focus-visible:ring-offset-2 focus-visible:ring-offset-(--bg)',
        'transition-colors',
        className,
      )}
    />
  )
}
