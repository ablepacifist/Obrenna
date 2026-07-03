import { Zap } from 'lucide-react'
import { cn } from '../../lib/cn'
import { useMetricsPreference } from '../../context/MetricsPreferenceContext'
import { useTokenRate } from '../../context/TokenRateContext'

/**
 * Bottom-right live tokens/second indicator. Only renders when the user has
 * enabled "Show tokens / second" in Settings → Appearance and there is a rate
 * to show (during streaming or after a turn completes). Fixed to the viewport
 * and pointer-events-none so it never blocks the composer or artifact panel.
 */
export function TokenRateIndicator() {
  const { showTokensPerSecond } = useMetricsPreference()
  const { tokensPerSecond, isStreaming, finalTokensPerSecond } = useTokenRate()

  if (!showTokensPerSecond) return null

  const live = isStreaming && tokensPerSecond != null
  const value = live ? tokensPerSecond : finalTokensPerSecond
  if (value == null) return null

  return (
    <div
      className={cn(
        'fixed bottom-3 right-3 z-50 pointer-events-none select-none',
        'inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] font-medium',
        'bg-(--surface)/95 border-(--border) shadow-sm backdrop-blur-sm',
        live ? 'text-(--ink)' : 'text-(--ink-faint)',
      )}
      title={live ? 'Generating…' : 'Last turn generation speed (estimated)'}
    >
      <Zap
        className={cn('w-3 h-3', live ? 'text-(--accent) animate-pulse' : 'text-(--ink-faint)')}
        fill={live ? 'currentColor' : 'none'}
      />
      <span>
        {value} tok/s
      </span>
    </div>
  )
}