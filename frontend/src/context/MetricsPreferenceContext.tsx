import { createContext, useContext, useEffect, useState } from 'react'

const STORAGE_KEY = 'showTokensPerSecond'
const DEFAULT = false

function readStored(): boolean {
  if (typeof localStorage === 'undefined') return DEFAULT
  const v = localStorage.getItem(STORAGE_KEY)
  if (v === 'true') return true
  if (v === 'false') return false
  return DEFAULT
}

interface MetricsPreferenceContextValue {
  showTokensPerSecond: boolean
  setShowTokensPerSecond: (v: boolean) => void
}

const MetricsPreferenceContext = createContext<MetricsPreferenceContextValue>({
  showTokensPerSecond: DEFAULT,
  setShowTokensPerSecond: () => {},
})

export function MetricsPreferenceProvider({ children }: { children: React.ReactNode }) {
  const [showTokensPerSecond, setShow] = useState<boolean>(readStored)

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, String(showTokensPerSecond))
  }, [showTokensPerSecond])

  function setShowTokensPerSecond(v: boolean) {
    setShow(v)
  }

  return (
    <MetricsPreferenceContext.Provider value={{ showTokensPerSecond, setShowTokensPerSecond }}>
      {children}
    </MetricsPreferenceContext.Provider>
  )
}

export function useMetricsPreference() {
  return useContext(MetricsPreferenceContext)
}