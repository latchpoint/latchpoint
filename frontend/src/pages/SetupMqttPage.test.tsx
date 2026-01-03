import React from 'react'
import { describe, expect, it, vi } from 'vitest'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderWithProviders } from '@/test/render'
import SetupMqttPage from '@/pages/SetupMqttPage'

const onSubmit = vi.fn()
const onTest = vi.fn()
const onClearPassword = vi.fn()

vi.mock('@/features/setupMqtt/hooks/useSetupMqttModel', () => {
  return {
    useSetupMqttModel: () => ({
      isAdmin: true,
      error: null,
      notice: null,
      statusQuery: { data: null, isLoading: false, refetch: vi.fn() },
      settingsQuery: { data: null, isLoading: false, refetch: vi.fn() },
      updateSettings: { isPending: false },
      testConnection: { isPending: false },
      enabled: false,
      register: () => ({}),
      handleSubmit: (fn: any) => fn,
      setValue: vi.fn(),
      watch: () => ({
        enabled: false,
        host: '',
        port: '1883',
        username: '',
        password: '',
        useTls: false,
        tlsInsecure: false,
        clientId: '',
        keepaliveSeconds: '30',
        connectTimeoutSeconds: '5',
      }),
      errors: {},
      isSubmitting: false,
      onSubmit,
      onTest,
      onClearPassword,
    }),
  }
})

vi.mock('@/features/setupMqtt/components/SetupMqttCard', () => {
  return {
    SetupMqttCard: (props: any) => (
      <div>
        <div>Setup MQTT</div>
        <button type="button" onClick={() => props.onTest()}>
          Test
        </button>
        <button type="button" onClick={() => props.onClearPassword()}>
          Clear Password
        </button>
        <button type="button" onClick={() => props.onSubmit(props.watch())}>
          Save
        </button>
      </div>
    ),
  }
})

describe('SetupMqttPage', () => {
  it('wires actions to the model', async () => {
    const user = userEvent.setup()
    renderWithProviders(<SetupMqttPage />)

    await user.click(screen.getByRole('button', { name: /test/i }))
    await user.click(screen.getByRole('button', { name: /clear password/i }))
    await user.click(screen.getByRole('button', { name: /save/i }))

    expect(onTest).toHaveBeenCalledTimes(1)
    expect(onClearPassword).toHaveBeenCalledTimes(1)
    expect(onSubmit).toHaveBeenCalledTimes(1)
  })
})

