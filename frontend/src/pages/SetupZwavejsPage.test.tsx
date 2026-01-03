import React from 'react'
import { describe, expect, it, vi } from 'vitest'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderWithProviders } from '@/test/render'
import SetupZwavejsPage from '@/pages/SetupZwavejsPage'

const onSubmit = vi.fn()
const onTest = vi.fn()
const onSync = vi.fn()

vi.mock('@/features/setupZwavejs/hooks/useSetupZwavejsModel', () => {
  return {
    useSetupZwavejsModel: () => ({
      isAdmin: true,
      error: null,
      notice: null,
      statusQuery: { data: null, isLoading: false, refetch: vi.fn() },
      settingsQuery: { data: null, isLoading: false, refetch: vi.fn() },
      updateSettings: { isPending: false },
      testConnection: { isPending: false },
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
      onSubmit,
      onTest,
      onSync,
    }),
  }
})

vi.mock('@/features/setupZwavejs/components/SetupZwavejsCard', () => {
  return {
    SetupZwavejsCard: (props: any) => (
      <div>
        <div>Setup Z-Wave JS</div>
        <button type="button" onClick={() => props.onTest()}>
          Test
        </button>
        <button type="button" onClick={() => props.onSync()}>
          Sync
        </button>
        <button type="button" onClick={() => props.onSubmit(props.watch())}>
          Save
        </button>
      </div>
    ),
  }
})

describe('SetupZwavejsPage', () => {
  it('wires actions to the model', async () => {
    const user = userEvent.setup()
    renderWithProviders(<SetupZwavejsPage />)

    await user.click(screen.getByRole('button', { name: /test/i }))
    await user.click(screen.getByRole('button', { name: /sync/i }))
    await user.click(screen.getByRole('button', { name: /save/i }))

    expect(onTest).toHaveBeenCalledTimes(1)
    expect(onSync).toHaveBeenCalledTimes(1)
    expect(onSubmit).toHaveBeenCalledTimes(1)
  })
})

