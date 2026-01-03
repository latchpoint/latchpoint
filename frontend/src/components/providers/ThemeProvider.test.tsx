import React from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { ThemeProvider } from './ThemeProvider'
import { useThemeStore } from '@/stores/themeStore'

describe('ThemeProvider', () => {
  beforeEach(() => {
    localStorage.clear()
    useThemeStore.setState({ theme: 'system' })
    document.documentElement.classList.remove('light', 'dark')
  })

  it('applies explicit theme to documentElement', async () => {
    useThemeStore.setState({ theme: 'dark' })
    render(
      <ThemeProvider>
        <div>Child</div>
      </ThemeProvider>
    )

    expect(screen.getByText('Child')).toBeInTheDocument()
    expect(document.documentElement.classList.contains('dark')).toBe(true)
    expect(document.documentElement.classList.contains('light')).toBe(false)
  })

  it('applies system theme using matchMedia', () => {
    const addEventListener = vi.fn()
    const removeEventListener = vi.fn()

    Object.defineProperty(window, 'matchMedia', {
      writable: true,
      value: () => ({
        matches: true,
        addEventListener,
        removeEventListener,
      }),
    })

    useThemeStore.setState({ theme: 'system' })
    const { unmount } = render(
      <ThemeProvider>
        <div>Child</div>
      </ThemeProvider>
    )

    expect(document.documentElement.classList.contains('dark')).toBe(true)
    expect(addEventListener).toHaveBeenCalled()

    unmount()
    expect(removeEventListener).toHaveBeenCalled()
  })
})
