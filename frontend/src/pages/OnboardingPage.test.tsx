import { describe, expect, it, vi } from 'vitest'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { OnboardingPage } from '@/pages/OnboardingPage'
import { renderWithProviders } from '@/test/render'

vi.mock('@/hooks/useOnboardingQueries', () => {
  return {
    useOnboardingCreateMutation: () => ({
      mutateAsync: vi.fn().mockResolvedValue(undefined),
    }),
  }
})

describe('OnboardingPage', () => {
  it('shows validation errors for invalid inputs', async () => {
    renderWithProviders(<OnboardingPage />)

    const user = userEvent.setup()
    await user.type(screen.getByLabelText(/admin email/i, { selector: 'input' }), 'test@example.com')
    await user.type(screen.getByLabelText(/admin password/i, { selector: 'input' }), 'short')
    await user.click(screen.getByRole('button', { name: /create admin/i }))

    expect(await screen.findByText(/at least 8 characters/i)).toBeInTheDocument()
  })

  it('toggles password visibility', async () => {
    renderWithProviders(<OnboardingPage />)

    const user = userEvent.setup()
    const passwordInput = screen.getByLabelText(/admin password/i, { selector: 'input' })

    expect(passwordInput).toHaveAttribute('type', 'password')
    await user.click(screen.getByRole('button', { name: /show password/i }))
    expect(passwordInput).toHaveAttribute('type', 'text')
  })
})
