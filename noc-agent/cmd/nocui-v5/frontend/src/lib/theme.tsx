import React, { createContext, useContext, useEffect, useState } from 'react'

export type Theme = 'dark' | 'light' | 'system'

interface ThemeCtx {
  theme: Theme
  setTheme: (t: Theme) => void
  resolved: 'dark' | 'light'
}

const Ctx = createContext<ThemeCtx | null>(null)
const STORAGE_KEY = 'argus.theme'

function getSystemTheme(): 'dark' | 'light' {
  if (typeof window === 'undefined') return 'dark'
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

function applyClass(t: 'dark' | 'light') {
  const root = document.documentElement
  root.classList.remove('dark', 'light')
  root.classList.add(t)
  root.style.colorScheme = t
}

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [theme, setThemeState] = useState<Theme>(() => {
    if (typeof window === 'undefined') return 'dark'
    return (localStorage.getItem(STORAGE_KEY) as Theme) || 'dark'
  })
  const [resolved, setResolved] = useState<'dark' | 'light'>(() =>
    theme === 'system' ? getSystemTheme() : (theme as 'dark' | 'light')
  )

  useEffect(() => {
    const target: 'dark' | 'light' = theme === 'system' ? getSystemTheme() : (theme as 'dark' | 'light')
    setResolved(target)
    applyClass(target)
    localStorage.setItem(STORAGE_KEY, theme)
  }, [theme])

  useEffect(() => {
    if (theme !== 'system') return
    const mq = window.matchMedia('(prefers-color-scheme: dark)')
    const handler = () => {
      const t = mq.matches ? 'dark' : 'light'
      setResolved(t)
      applyClass(t)
    }
    mq.addEventListener('change', handler)
    return () => mq.removeEventListener('change', handler)
  }, [theme])

  return <Ctx.Provider value={{ theme, setTheme: setThemeState, resolved }}>{children}</Ctx.Provider>
}

export function useTheme(): ThemeCtx {
  const c = useContext(Ctx)
  if (!c) throw new Error('useTheme outside provider')
  return c
}
