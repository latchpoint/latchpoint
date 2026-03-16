import React from 'react'
import { describe, expect, it, vi } from 'vitest'
import { screen } from '@testing-library/react'
import { renderWithProviders } from '@/test/render'
import SetupMqttPage from '@/pages/SetupMqttPage'

vi.mock('@/features/setupMqtt/hooks/useSetupMqttModel', () => {
  return {
    useSetupMqttModel: () => ({
      isAdmin: true,
      error: null,
      notice: null,
      statusQuery: { data: null, isLoading: false, refetch: vi.fn() },
      settingsQuery: { data: null, isLoading: false, refetch: vi.fn() },
      enabled: false,
      register: () => ({}),
      handleSubmit: (fn: any) => fn,
      setValue: vi.fn(),
      watch: () => ({
        enabled: false,
        host: '',
        port: '1883',
        username: '',
        useTls: false,
        tlsInsecure: false,
        clientId: '',
        keepaliveSeconds: '30',
        connectTimeoutSeconds: '5',
      }),
      errors: {},
      isSubmitting: false,
    }),
  }
})

vi.mock('@/features/setupMqtt/components/SetupMqttCard', () => {
  return {
    SetupMqttCard: () => (
      <div>
        <div>Setup MQTT</div>
      </div>
    ),
  }
})

describe('SetupMqttPage', () => {
  it('renders the setup card', () => {
    renderWithProviders(<SetupMqttPage />)
    expect(screen.getByText('Setup MQTT')).toBeDefined()
  })
})
