import React from 'react'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { renderWithProviders } from '@/test/render'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Routes } from '@/lib/constants'
import SetupWizardPage from '@/pages/SetupWizardPage'

const navigate = vi.fn()
let lastOptions: any
let model: any

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<any>('react-router-dom')
  return {
    ...actual,
    useNavigate: () => navigate,
  }
})

vi.mock('@/features/setupWizard/hooks/useSetupWizardModel', () => {
  return {
    useSetupWizardModel: (options: any) => {
      lastOptions = options
      return model
    },
  }
})

vi.mock('@/features/setupWizard/components/SetupWizardCard', () => {
  return {
    SetupWizardCard: (props: any) => (
      <div>
        <div>SetupWizardCard</div>
        <button type="button" onClick={props.onLogout}>
          Logout
        </button>
      </div>
    ),
  }
})

describe('SetupWizardPage', () => {
  beforeEach(() => {
    navigate.mockReset()
    lastOptions = null
    model = {
      isAdmin: true,
      error: null,
      allowedStates: [],
      armableStates: [],
      setAllowedStates: vi.fn(),
      register: vi.fn(),
      handleSubmit: vi.fn(),
      formErrors: {},
      isSubmitting: false,
      onSubmit: vi.fn(),
      logout: vi.fn(),
    }
  })

  it('navigates to MQTT step on success', () => {
    renderWithProviders(<SetupWizardPage />)

    expect(lastOptions).toBeTruthy()
    lastOptions.onSuccess()
    expect(navigate).toHaveBeenCalledWith(Routes.SETUP_MQTT, { replace: true })
  })

  it('wires logout to model.logout()', async () => {
    const user = userEvent.setup()
    renderWithProviders(<SetupWizardPage />)

    await user.click(screen.getByRole('button', { name: /logout/i }))
    expect(model.logout).toHaveBeenCalled()
  })
})

