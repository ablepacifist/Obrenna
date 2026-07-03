import { createContext, useContext, useEffect, useState } from 'react'

export type WordAnimationStyle = 'claude' | 'clean' | 'scramble' | 'none'

const VALID_STYLES: WordAnimationStyle[] = ['claude', 'clean', 'scramble', 'none']
const STORAGE_KEY = 'wordAnimationStyle'
const DEFAULT_STYLE: WordAnimationStyle = 'claude'

function validateStyle(value: string | null): WordAnimationStyle {
  if (value && VALID_STYLES.includes(value as WordAnimationStyle)) {
    return value as WordAnimationStyle
  }
  return DEFAULT_STYLE
}

interface AnimationPreferenceContextValue {
  style: WordAnimationStyle
  setStyle: (s: WordAnimationStyle) => void
}

const AnimationPreferenceContext = createContext<AnimationPreferenceContextValue>({
  style: DEFAULT_STYLE,
  setStyle: () => {},
})

export function AnimationPreferenceProvider({ children }: { children: React.ReactNode }) {
  const [style, setStyleState] = useState<WordAnimationStyle>(
    () => validateStyle(localStorage.getItem(STORAGE_KEY))
  )

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, style)
  }, [style])

  function setStyle(s: WordAnimationStyle) {
    setStyleState(s)
  }

  return (
    <AnimationPreferenceContext.Provider value={{ style, setStyle }}>
      {children}
    </AnimationPreferenceContext.Provider>
  )
}

export function useAnimationPreference() {
  return useContext(AnimationPreferenceContext)
}
