import { describe, expect, it, vi } from 'vitest'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { LoginPage } from '@/pages/LoginPage'
import { renderWithProviders } from '@/test/render'

vi.mock('@/hooks/useAuth', () => {
  return {
    useAuth: () => ({
      login: vi.fn().mockResolvedValue(undefined),
      isLoading: false,
      error: null,
      clearError: vi.fn(),
    }),
  }
})

describe('LoginPage', () => {
  it('validates inputs before submit', async () => {
    renderWithProviders(<LoginPage />)

    const user = userEvent.setup()
    await user.type(screen.getByLabelText(/email/i, { selector: 'input' }), 'test@example.com')
    await user.click(screen.getByRole('button', { name: /sign in/i }))

    expect(await screen.findByText(/password is required/i)).toBeInTheDocument()
  })

  it('toggles password visibility', async () => {
    renderWithProviders(<LoginPage />)

    const user = userEvent.setup()
    const passwordInput = screen.getByLabelText(/password/i, { selector: 'input' })

    expect(passwordInput).toHaveAttribute('type', 'password')
    await user.click(screen.getByRole('button', { name: /show password/i }))
    expect(passwordInput).toHaveAttribute('type', 'text')
    await user.click(screen.getByRole('button', { name: /hide password/i }))
    expect(passwordInput).toHaveAttribute('type', 'password')
  })
})
