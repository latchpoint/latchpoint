import { beforeEach, describe, expect, it, vi } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { renderWithProviders } from '@/test/render'
import { SecuritySettingsCard, SECURITY_SETTINGS } from './SecuritySettingsCard'

const mutateAsync = vi.fn()

vi.mock('@/hooks/useSettingsQueries', () => {
  return {
    useSystemConfigQuery: () => ({
      isLoading: false,
      data: SECURITY_SETTINGS.map((s) => ({
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

describe('SecuritySettingsCard', () => {
  beforeEach(() => {
    mutateAsync.mockReset()
  })

  it('renders alarm-code security inputs for admins', () => {
    renderWithProviders(<SecuritySettingsCard isAdmin />)

    for (const s of SECURITY_SETTINGS) {
      expect(screen.getByLabelText(s.key)).toBeTruthy()
    }
  })

  it('hides everything for non-admins', () => {
    const { container } = renderWithProviders(<SecuritySettingsCard isAdmin={false} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('validates value bounds and shows an error', async () => {
    const user = userEvent.setup()
    renderWithProviders(<SecuritySettingsCard isAdmin />)

    await user.clear(screen.getByLabelText('alarm_code.lockout_threshold'))
    await user.type(screen.getByLabelText('alarm_code.lockout_threshold'), '99999')

    await user.click(screen.getByRole('button', { name: 'Save' }))

    expect(await screen.findByText(/must be between/i)).toBeTruthy()
    expect(mutateAsync).not.toHaveBeenCalled()
  })

  it('batches multiple updates into one mutation call', async () => {
    const user = userEvent.setup()
    mutateAsync.mockResolvedValueOnce([])
    renderWithProviders(<SecuritySettingsCard isAdmin />)

    await user.clear(screen.getByLabelText('alarm_code.lockout_threshold'))
    await user.type(screen.getByLabelText('alarm_code.lockout_threshold'), '3')
    await user.clear(screen.getByLabelText('alarm_code.lockout_duration_seconds'))
    await user.type(screen.getByLabelText('alarm_code.lockout_duration_seconds'), '120')

    await user.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() => expect(mutateAsync).toHaveBeenCalledTimes(1))
    const payload = mutateAsync.mock.calls[0]?.[0] as Array<{ key: string; changes: { value: unknown } }>
    expect(payload).toEqual([
      { key: 'alarm_code.lockout_threshold', changes: { value: 3 } },
      { key: 'alarm_code.lockout_duration_seconds', changes: { value: 120 } },
    ])
  })
})
