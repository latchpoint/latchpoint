import React, { useState } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { FeatureErrorBoundary } from '@/components/providers/FeatureErrorBoundary'
import { renderWithProviders } from '@/test/render'

function Exploder({ shouldThrow }: { shouldThrow: boolean }) {
  if (shouldThrow) {
    throw new Error('boom')
  }
  return <div>Healthy</div>
}

function Harness({ onRetry }: { onRetry: () => void }) {
  const [shouldThrow, setShouldThrow] = useState(true)
  return (
    <FeatureErrorBoundary
      feature="Thing"
      onRetry={() => {
        setShouldThrow(false)
        onRetry()
      }}
    >
      <Exploder shouldThrow={shouldThrow} />
    </FeatureErrorBoundary>
  )
}

describe('FeatureErrorBoundary', () => {
  it('renders fallback UI and recovers on retry', async () => {
    const user = userEvent.setup()
    const onRetry = vi.fn()

    // Silence expected error logging during test.
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {})

    renderWithProviders(<Harness onRetry={onRetry} />)

    expect(await screen.findByText(/failed to load thing/i)).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /try again/i }))

    expect(await screen.findByText('Healthy')).toBeInTheDocument()
    expect(onRetry).toHaveBeenCalledTimes(1)

    consoleError.mockRestore()
  })
})

