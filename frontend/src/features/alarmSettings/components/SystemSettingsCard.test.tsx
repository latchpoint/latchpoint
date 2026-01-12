import { beforeEach, describe, expect, it, vi } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { renderWithProviders } from '@/test/render'
import { SystemSettingsCard, SYSTEM_SETTINGS } from './SystemSettingsCard'

const mutateAsync = vi.fn()

vi.mock('@/hooks/useSettingsQueries', () => {
  return {
    useSystemConfigQuery: () => ({
      isLoading: false,
      data: SYSTEM_SETTINGS.map((s) => ({
        key: s.key,
        name: s.key,
        value_type: 'integer',
        value: s.defaultValue,
        description: 'desc',
        modified_by_id: null,
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
      })),
    }),
    useBatchUpdateSystemConfigMutation: () => ({
      isPending: false,
      mutateAsync,
    }),
  }
})

describe('SystemSettingsCard', () => {
  beforeEach(() => {
    mutateAsync.mockReset()
  })

  it('renders retention inputs for admins', () => {
    renderWithProviders(<SystemSettingsCard isAdmin />)

    for (const s of SYSTEM_SETTINGS) {
      expect(screen.getByLabelText(s.key)).toBeTruthy()
    }
  })

  it('shows Save/Reset actions after a change', async () => {
    const user = userEvent.setup()
    renderWithProviders(<SystemSettingsCard isAdmin />)

    await user.clear(screen.getByLabelText('events.retention_days'))
    await user.type(screen.getByLabelText('events.retention_days'), '0')

    expect(screen.getByRole('button', { name: 'Save' })).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Reset' })).toBeTruthy()
  })

  it('validates value bounds and shows an error', async () => {
    const user = userEvent.setup()
    renderWithProviders(<SystemSettingsCard isAdmin />)

    await user.clear(screen.getByLabelText('door_code_events.retention_days'))
    await user.type(screen.getByLabelText('door_code_events.retention_days'), '999999')

    await user.click(screen.getByRole('button', { name: 'Save' }))

    expect(await screen.findByText(/must be between/i)).toBeTruthy()
    expect(mutateAsync).not.toHaveBeenCalled()
  })

  it('batches multiple updates into one mutation call', async () => {
    const user = userEvent.setup()
    mutateAsync.mockResolvedValueOnce([])
    renderWithProviders(<SystemSettingsCard isAdmin />)

    await user.clear(screen.getByLabelText('notification_logs.retention_days'))
    await user.type(screen.getByLabelText('notification_logs.retention_days'), '0')
    await user.clear(screen.getByLabelText('notification_deliveries.retention_days'))
    await user.type(screen.getByLabelText('notification_deliveries.retention_days'), '1')

    await user.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() => expect(mutateAsync).toHaveBeenCalledTimes(1))
    const payload = mutateAsync.mock.calls[0]?.[0] as Array<{ key: string; changes: { value: unknown } }>
    expect(payload).toEqual([
      { key: 'notification_logs.retention_days', changes: { value: 0 } },
      { key: 'notification_deliveries.retention_days', changes: { value: 1 } },
    ])
  })
})
