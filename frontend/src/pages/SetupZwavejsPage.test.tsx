import React from 'react'
import { describe, expect, it, vi } from 'vitest'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderWithProviders } from '@/test/render'
import SetupZwavejsPage from '@/pages/SetupZwavejsPage'

const onSync = vi.fn()

vi.mock('@/features/setupZwavejs/hooks/useSetupZwavejsModel', () => {
  return {
    useSetupZwavejsModel: () => ({
      isAdmin: true,
      error: null,
      notice: null,
      statusQuery: { data: null, isLoading: false, refetch: vi.fn() },
      settingsQuery: { data: null, isLoading: false, refetch: vi.fn() },
      syncEntities: { isPending: false },
      enabled: false,
      register: () => ({}),
      handleSubmit: (fn: any) => fn,
      setValue: vi.fn(),
      watch: () => ({
        enabled: false,
        wsUrl: 'ws://localhost:3000',
        connectTimeoutSeconds: '5',
        reconnectMinSeconds: '1',
        reconnectMaxSeconds: '30',
      }),
      errors: {},
      isSubmitting: false,
      onSync,
    }),
  }
})

vi.mock('@/features/setupZwavejs/components/SetupZwavejsCard', () => {
  return {
    SetupZwavejsCard: (props: any) => (
      <div>
        <div>Setup Z-Wave JS</div>
        <button type="button" onClick={() => props.onSync()}>
          Sync
        </button>
      </div>
    ),
  }
})

describe('SetupZwavejsPage', () => {
  it('wires sync action to the model', async () => {
    const user = userEvent.setup()
    renderWithProviders(<SetupZwavejsPage />)

    await user.click(screen.getByRole('button', { name: /sync/i }))

    expect(onSync).toHaveBeenCalledTimes(1)
  })
})
