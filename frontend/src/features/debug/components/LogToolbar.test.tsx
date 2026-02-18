import React from 'react'
import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { LogToolbar } from './LogToolbar'

const defaultProps = {
  paused: false,
  autoScroll: true,
  levelFilter: 0,
  onPauseToggle: vi.fn(),
  onAutoScrollToggle: vi.fn(),
  onLevelFilterChange: vi.fn(),
  onClear: vi.fn(),
}

function renderToolbar(overrides: Partial<typeof defaultProps> = {}) {
  const props = { ...defaultProps, ...overrides }
  // Reset mocks for each render
  Object.values(props).forEach((v) => {
    if (typeof v === 'function' && 'mockClear' in v) {
      ;(v as ReturnType<typeof vi.fn>).mockClear()
    }
  })
  return render(<LogToolbar {...props} />)
}

describe('LogToolbar', () => {
  it('renders all level filter buttons', () => {
    renderToolbar()
    const labels = ['All', 'Debug', 'Info', 'Warning', 'Error', 'Critical']
    for (const label of labels) {
      expect(screen.getByRole('button', { name: label })).toBeInTheDocument()
    }
  })

  it('highlights the active level filter', () => {
    renderToolbar({ levelFilter: 20 }) // INFO = 20
    const infoButton = screen.getByRole('button', { name: 'Info' })
    expect(infoButton.className).toContain('bg-primary')
  })

  it('calls onLevelFilterChange on click', async () => {
    const onLevelFilterChange = vi.fn()
    renderToolbar({ onLevelFilterChange })
    await userEvent.click(screen.getByRole('button', { name: 'Warning' }))
    expect(onLevelFilterChange).toHaveBeenCalledWith(30) // WARNING = 30
  })

  it('calls onPauseToggle on click', async () => {
    const onPauseToggle = vi.fn()
    renderToolbar({ onPauseToggle })
    await userEvent.click(screen.getByTitle('Pause streaming'))
    expect(onPauseToggle).toHaveBeenCalledOnce()
  })

  it('shows correct pause/resume title', () => {
    const { unmount } = renderToolbar({ paused: false })
    expect(screen.getByTitle('Pause streaming')).toBeInTheDocument()
    unmount()

    renderToolbar({ paused: true })
    expect(screen.getByTitle('Resume streaming')).toBeInTheDocument()
  })

  it('calls onAutoScrollToggle on click', async () => {
    const onAutoScrollToggle = vi.fn()
    renderToolbar({ onAutoScrollToggle })
    await userEvent.click(screen.getByTitle('Auto-scroll: on'))
    expect(onAutoScrollToggle).toHaveBeenCalledOnce()
  })

  it('calls onClear on click', async () => {
    const onClear = vi.fn()
    renderToolbar({ onClear })
    await userEvent.click(screen.getByTitle('Clear logs'))
    expect(onClear).toHaveBeenCalledOnce()
  })
})
