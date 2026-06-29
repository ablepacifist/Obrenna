import type { ButtonHTMLAttributes } from 'react'
import { cn } from '../../lib/cn'

type Variant = 'primary' | 'secondary' | 'ghost' | 'danger'

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant
}

export function Button({ variant = 'primary', className, children, ...p }: ButtonProps) {
  const base =
    'inline-flex items-center justify-center gap-2 h-9 px-3.5 rounded-md text-[13px] font-medium transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-(--accent) focus-visible:ring-offset-2 focus-visible:ring-offset-(--bg) disabled:opacity-50 disabled:pointer-events-none'
  const variants: Record<Variant, string> = {
    primary: 'bg-(--accent) text-(--accent-ink) hover:brightness-110',
    secondary: 'bg-(--surface-2) text-(--ink) border border-(--border) hover:bg-(--border)',
    ghost: 'text-(--ink) hover:bg-(--surface-2)',
    danger: 'text-(--err) hover:bg-(--surface-2)',
  }
  return (
    <button className={cn(base, variants[variant], className)} {...p}>
      {children}
    </button>
  )
}
