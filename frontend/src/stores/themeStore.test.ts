import { describe, expect, it, beforeEach } from 'vitest'
import { useThemeStore } from '@/stores'

describe('themeStore', () => {
  beforeEach(() => {
    localStorage.clear()
    useThemeStore.setState({ theme: 'system' })
  })

  it('defaults to system and updates theme', () => {
    expect(useThemeStore.getState().theme).toBe('system')
    useThemeStore.getState().setTheme('dark')
    expect(useThemeStore.getState().theme).toBe('dark')
  })

  it('persists theme to localStorage', () => {
    useThemeStore.getState().setTheme('light')
    const raw = localStorage.getItem('alarm-theme')
    expect(raw).toContain('light')
  })
})

