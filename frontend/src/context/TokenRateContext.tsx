import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react'
import { useAgentEvent } from '../hooks/useAgentEvent'

interface TokenRateContextValue {
  /** Live estimated tokens/sec during the active turn (null until first token). */
  tokensPerSecond: number | null
  /** True while a turn is actively streaming tokens. */
  isStreaming: boolean
  /** Frozen final tokens/sec from the most recently completed turn (null until it ends). */
  finalTokensPerSecond: number | null
}

const TokenRateContext = createContext<TokenRateContextValue>({
  tokensPerSecond: null,
  isStreaming: false,
  finalTokensPerSecond: null,
})

// Standard ~4 chars/token heuristic. The streaming layer coalesces many model
// tokens into each `token` event (TokenCoalescer), so counting events would
// badly undercount; estimating from text length gives a rate that matches the
// order-of-magnitude a real tokenizer reports and reflects true decode speed.
const CHARS_PER_TOKEN = 4
const TICK_MS = 200

function estimateTokens(text: string): number {
  if (!text) return 0
  return Math.max(1, Math.round(text.length / CHARS_PER_TOKEN))
}

interface AgentEvent {
  chat_id: string
  message_id: string
  type: string
  payload: Record<string, unknown>
}

export function TokenRateProvider({ children }: { children: React.ReactNode }) {
  // Per-turn tracking state — mutated on every token event without triggering
  // a React re-render per token. Display state below is updated from these.
  const streamingIdRef = useRef<string | null>(null)
  const firstTokenAtRef = useRef<number | null>(null)
  const tokenCountRef = useRef<number>(0)
  const streamingRef = useRef<boolean>(false)

  const [tokensPerSecond, setTokensPerSecond] = useState<number | null>(null)
  const [isStreaming, setIsStreaming] = useState(false)
  const [finalTokensPerSecond, setFinalTokensPerSecond] = useState<number | null>(null)

  const recompute = useCallback(() => {
    const first = firstTokenAtRef.current
    if (first == null) {
      setTokensPerSecond(null)
      return
    }
    const elapsed = (performance.now() - first) / 1000
    setTokensPerSecond(elapsed > 0 ? Math.round(tokenCountRef.current / elapsed) : null)
  }, [])

  const freezeFinal = useCallback(() => {
    const first = firstTokenAtRef.current
    const elapsed = first != null ? (performance.now() - first) / 1000 : 0
    setFinalTokensPerSecond(elapsed > 0 ? Math.round(tokenCountRef.current / elapsed) : null)
  }, [])

  const handleEvent = useCallback((event: AgentEvent) => {
    if (event.type === 'token') {
      const text = event.payload.text as string
      if (!text) return
      const id = event.message_id
      // A different assistant message id means a new turn: reset the tracker.
      if (id && id !== streamingIdRef.current) {
        streamingIdRef.current = id
        firstTokenAtRef.current = performance.now()
        tokenCountRef.current = 0
        streamingRef.current = true
        setFinalTokensPerSecond(null)
        setIsStreaming(true)
      }
      tokenCountRef.current += estimateTokens(text)
      recompute()
    } else if (event.type === 'done') {
      const id = event.message_id
      if (!id || id !== streamingIdRef.current) return
      streamingRef.current = false
      setIsStreaming(false)
      freezeFinal()
    } else if (event.type === 'error') {
      // Turn ended without a clean done — stop streaming and freeze whatever
      // rate was observed (may be null if no tokens streamed before the error).
      if (!streamingRef.current) return
      streamingRef.current = false
      setIsStreaming(false)
      freezeFinal()
    }
  }, [recompute, freezeFinal])

  useAgentEvent(handleEvent)

  // While streaming, advance the displayed rate on a fixed cadence so the
  // denominator keeps moving even between token batches.
  useEffect(() => {
    if (!isStreaming) return
    const t = setInterval(recompute, TICK_MS)
    return () => clearInterval(t)
  }, [isStreaming, recompute])

  return (
    <TokenRateContext.Provider value={{ tokensPerSecond, isStreaming, finalTokensPerSecond }}>
      {children}
    </TokenRateContext.Provider>
  )
}

export function useTokenRate() {
  return useContext(TokenRateContext)
}