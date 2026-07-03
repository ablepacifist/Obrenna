import { Moon, Sun } from 'lucide-react'
import { useEffect, useState } from 'react'
import { cn } from '../../lib/cn'
import { useTheme } from '../../theme/ThemeProvider'
import { useAnimationPreference } from '../../context/AnimationPreferenceContext'
import type { WordAnimationStyle } from '../../context/AnimationPreferenceContext'
import { useMetricsPreference } from '../../context/MetricsPreferenceContext'
import { StreamedText } from '../chat/StreamedText'
import { StreamingScrambleText } from '../chat/StreamingScrambleText'

const PREVIEW_TEXT =
  'Lorem ipsum dolor sit amet, consectetur adipiscing elit. Sed do eiusmod tempor incididunt ut labore et dolore magna aliqua.'

function ScramblePreview() {
  const [previewText, setPreviewText] = useState(PREVIEW_TEXT.slice(0, 26))

  useEffect(() => {
    setPreviewText(PREVIEW_TEXT.slice(0, 26))
    const timer = window.setTimeout(() => setPreviewText(PREVIEW_TEXT), 420)
    return () => window.clearTimeout(timer)
  }, [])

  return <StreamingScrambleText text={previewText} active durationMs={420} />
}

export function AppearanceSettings() {
  const { theme, setTheme } = useTheme()
  const { style, setStyle } = useAnimationPreference()
  const { showTokensPerSecond, setShowTokensPerSecond } = useMetricsPreference()

  const themeOptions = [
    { id: 'light' as const, label: 'Light', icon: Sun },
    { id: 'dark' as const, label: 'Dark', icon: Moon },
    { id: 'system' as const, label: 'System', icon: Sun },
  ]

  const animationOptions: { id: WordAnimationStyle; label: string }[] = [
    { id: 'claude', label: 'Claude-like' },
    { id: 'clean', label: 'Clean Professional' },
    { id: 'scramble', label: 'Scramble Reveal' },
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

        <div className="mt-3 rounded-lg border border-(--border) bg-(--surface) px-4 py-3">
          <div className="mb-1 text-[11px] uppercase tracking-wide text-(--ink-faint)">
            Preview
          </div>
          <p className="text-[13px] leading-relaxed text-(--ink-muted)">
            {style === 'scramble' ? (
              <ScramblePreview key={style} />
            ) : (
              <StreamedText key={style} text={PREVIEW_TEXT} active />
            )}
          </p>
        </div>
      </div>

      <div className="mt-8">
        <h4 className="text-[14px] font-medium text-(--ink)">Generation speed</h4>
        <p className="mt-1 text-[12px] text-(--ink-muted) leading-relaxed">
          Show a live tokens-per-second counter in the bottom-right corner while
          the model writes. The rate is estimated from streamed text.
        </p>
        <div className="mt-3 flex items-center justify-between rounded-lg border border-(--border) bg-(--surface) px-4 py-3">
          <label className="text-[13px] font-medium text-(--ink)" htmlFor="show-tokens-per-second">
            Show tokens / second
          </label>
          <button
            id="show-tokens-per-second"
            role="switch"
            aria-checked={showTokensPerSecond}
            onClick={() => setShowTokensPerSecond(!showTokensPerSecond)}
            className={cn(
              'relative inline-flex h-5 w-9 items-center rounded-full transition-colors',
              'focus:outline-none focus-visible:ring-2 focus-visible:ring-(--accent) focus-visible:ring-offset-2',
              showTokensPerSecond ? 'bg-(--accent)' : 'bg-(--border)',
            )}
          >
            <span
              className={cn(
                'inline-block h-3 w-3 transform rounded-full bg-white transition-transform',
                showTokensPerSecond ? 'translate-x-4' : 'translate-x-0.5',
              )}
            />
          </button>
        </div>
      </div>
    </div>
  )
}
