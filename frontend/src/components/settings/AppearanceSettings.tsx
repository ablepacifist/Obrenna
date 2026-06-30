import { Moon, Sun } from 'lucide-react'
import { cn } from '../../lib/cn'
import { useTheme } from '../../theme/ThemeProvider'
import { useAnimationPreference } from '../../context/AnimationPreferenceContext'
import type { WordAnimationStyle } from '../../context/AnimationPreferenceContext'

export function AppearanceSettings() {
  const { theme, setTheme } = useTheme()
  const { style, setStyle } = useAnimationPreference()

  const themeOptions = [
    { id: 'light' as const, label: 'Light', icon: Sun },
    { id: 'dark' as const, label: 'Dark', icon: Moon },
    { id: 'system' as const, label: 'System', icon: Sun },
  ]

  const animationOptions: { id: WordAnimationStyle; label: string }[] = [
    { id: 'claude', label: 'Claude-like' },
    { id: 'clean', label: 'Clean Professional' },
    { id: 'none', label: 'None' },
  ]

  return (
    <div>
      <h3 className="text-[18px] font-semibold tracking-tight text-(--ink)">Appearance</h3>
      <p className="mt-1 text-[13px] text-(--ink-muted) leading-relaxed">
        Choose how the workspace looks. You can change this any time.
      </p>
      <div className="mt-5 inline-flex rounded-lg border border-(--border) bg-(--surface) p-1">
        {themeOptions.map(o => {
          const I = o.icon
          const active = theme === o.id
          return (
            <button
              key={o.id}
              onClick={() => setTheme(o.id)}
              className={cn(
                'h-9 px-3 rounded-md text-[13px] inline-flex items-center gap-2 focus:outline-none focus-visible:ring-2 focus-visible:ring-(--accent)',
                active ? 'bg-(--surface-2) text-(--ink) font-medium' : 'text-(--ink-muted)',
              )}
            >
              <I className="w-3.5 h-3.5" /> {o.label}
            </button>
          )
        })}
      </div>

      <div className="mt-8">
        <h4 className="text-[14px] font-medium text-(--ink)">Word animation</h4>
        <p className="mt-1 text-[12px] text-(--ink-muted) leading-relaxed">
          Choose how assistant messages reveal their text.
        </p>
        <div className="mt-3 inline-flex rounded-lg border border-(--border) bg-(--surface) p-1">
          {animationOptions.map(o => {
            const active = style === o.id
            return (
              <button
                key={o.id}
                onClick={() => setStyle(o.id)}
                className={cn(
                  'h-9 px-3 rounded-md text-[13px] focus:outline-none focus-visible:ring-2 focus-visible:ring-(--accent)',
                  active ? 'bg-(--surface-2) text-(--ink) font-medium' : 'text-(--ink-muted)',
                )}
              >
                {o.label}
              </button>
            )
          })}
        </div>
      </div>
    </div>
  )
}
