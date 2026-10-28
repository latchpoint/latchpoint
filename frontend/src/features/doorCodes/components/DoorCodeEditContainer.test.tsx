import { describe, expect, it, vi } from 'vitest'
import { fireEvent, screen, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { server } from '@/test/msw/server'
import { renderWithProviders } from '@/test/render'
import { useDoorCodesQuery } from '@/hooks/useDoorCodesQueries'
import { DoorCodeEditContainer } from './DoorCodeEditContainer'
import type { DoorCode } from '@/types'

const PAGE_USER_ID = 'selected-user'
const NOTICE = 'This code changed on the server. Your unsaved changes are kept.'

function makeCode(overrides: Partial<DoorCode> = {}): DoorCode {
  return {
    id: 7,
    userId: '00000000-0000-0000-0000-000000000001',
    userDisplayName: 'Test',
    source: 'manual',
    label: 'Front',
    codeType: 'temporary',
    pin: null,
    pinLength: 4,
    isActive: true,
    maxUses: null,
    usesCount: 0,
    startAt: null,
    endAt: null,
    daysOfWeek: 127,
    windowStart: '08:00',
    windowEnd: '17:00',
    lastUsedAt: null,
    lastUsedLock: null,
    lockAssignments: [{ id: 1, lockEntityId: 'lock.front_door' }],
    lockEntityIds: ['lock.front_door'],
    lockSlotAssignments: [{ lockEntityId: 'lock.front_door', slotIndex: 3 }],
    pushState: 'pushed',
    lastPushError: '',
    lastPushAttemptAt: '2026-10-28T10:00:00Z',
    createdAt: '',
    updatedAt: '',
    ...overrides,
  }
}

// The edit form fed from the real door codes query, the way DoorCodeCard gets
// its code on the page.
function EditFormFromQuery() {
  const codesQuery = useDoorCodesQuery({ userId: PAGE_USER_ID, isAdmin: true })
  const code = codesQuery.data?.[0]
  if (!code) return null
  return (
    <DoorCodeEditContainer
      code={code}
      locks={[]}
      locksIsLoading={false}
      locksError={null}
      isSaving={false}
      isDeleting={false}
      onClose={vi.fn()}
      onUpdate={vi.fn()}
      onDelete={vi.fn()}
    />
  )
}

// Serves serverCode from the codes endpoint. Tests change it, then refetch.
function serveCode(initial: DoorCode) {
  const state = { code: initial }
  server.use(http.get('/api/door-codes/', () => HttpResponse.json({ data: [state.code] })))
  return state
}

const labelInput = () => screen.getByLabelText('Label') as HTMLInputElement
const newCodeInput = () => screen.getByLabelText('New code (optional)') as HTMLInputElement
const maxUsesInput = () => screen.getByLabelText('Max uses (optional)') as HTMLInputElement
const windowEndInput = () => screen.getByLabelText('Time window end (optional)') as HTMLInputElement
const sundayCheckbox = () => screen.getByRole('checkbox', { name: 'Sun' })
const activeSwitch = () => screen.getByRole('switch', { name: 'Active' })

describe('DoorCodeEditContainer', () => {
  it('imports', async () => {
    const mod = await import('./DoorCodeEditContainer')
    expect(mod).toBeTruthy()
  })

  it('keeps an edit in progress when the code changes on the server', async () => {
    const served = serveCode(makeCode())
    const { queryClient } = renderWithProviders(<EditFormFromQuery />)
    expect(await screen.findByDisplayValue('Front')).toBeTruthy()

    fireEvent.change(labelInput(), { target: { value: 'Back door' } })
    fireEvent.change(newCodeInput(), { target: { value: '2468' } })
    fireEvent.click(sundayCheckbox())

    // The scheduler retries the push and something else on the code changes.
    served.code = makeCode({ maxUses: 5, lastPushAttemptAt: '2026-10-28T10:05:00Z' })
    await queryClient.invalidateQueries()
    await waitFor(() => expect(maxUsesInput().value).toBe('5'))

    expect(labelInput().value).toBe('Back door')
    expect(newCodeInput().value).toBe('2468')
    expect(sundayCheckbox()).not.toBeChecked()
    expect(screen.queryByText(NOTICE)).toBeNull()
  })

  it("updates the fields the user hasn't edited", async () => {
    const served = serveCode(makeCode())
    const { queryClient } = renderWithProviders(<EditFormFromQuery />)
    expect(await screen.findByDisplayValue('Front')).toBeTruthy()
    expect(activeSwitch()).toHaveAttribute('aria-checked', 'true')

    fireEvent.change(labelInput(), { target: { value: 'Back door' } })

    // A refused delete in another tab turns the code off.
    served.code = makeCode({ isActive: false, maxUses: 5, windowEnd: '18:00', pushState: 'pending' })
    await queryClient.invalidateQueries()

    await waitFor(() => expect(activeSwitch()).toHaveAttribute('aria-checked', 'false'))
    expect(maxUsesInput().value).toBe('5')
    expect(windowEndInput().value).toBe('18:00')
    expect(labelInput().value).toBe('Back door')
  })

  it('shows a notice and keeps the edit when the server changes the same field', async () => {
    const served = serveCode(makeCode())
    const { queryClient } = renderWithProviders(<EditFormFromQuery />)
    expect(await screen.findByDisplayValue('Front')).toBeTruthy()

    fireEvent.change(labelInput(), { target: { value: 'Back door' } })

    served.code = makeCode({ label: 'Garage' })
    await queryClient.invalidateQueries()

    expect(await screen.findByRole('status')).toHaveTextContent(NOTICE)
    expect(labelInput().value).toBe('Back door')
  })

  it('puts the form back to the server values on discard', async () => {
    const served = serveCode(makeCode())
    const { queryClient } = renderWithProviders(<EditFormFromQuery />)
    expect(await screen.findByDisplayValue('Front')).toBeTruthy()

    fireEvent.change(labelInput(), { target: { value: 'Back door' } })
    fireEvent.change(newCodeInput(), { target: { value: '2468' } })
    fireEvent.click(sundayCheckbox())

    served.code = makeCode({ label: 'Garage', maxUses: 5 })
    await queryClient.invalidateQueries()
    expect(await screen.findByText(NOTICE)).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: 'Discard changes and reload' }))

    expect(labelInput().value).toBe('Garage')
    expect(newCodeInput().value).toBe('')
    expect(sundayCheckbox()).toBeChecked()
    expect(maxUsesInput().value).toBe('5')
    expect(screen.queryByText(NOTICE)).toBeNull()

    // With nothing edited the form follows the server again.
    served.code = makeCode({ label: 'Side gate', maxUses: 5 })
    await queryClient.invalidateQueries()
    await waitFor(() => expect(labelInput().value).toBe('Side gate'))
    expect(screen.queryByText(NOTICE)).toBeNull()
  })

  it('drops the notice once the edit matches the server', async () => {
    const served = serveCode(makeCode())
    const { queryClient } = renderWithProviders(<EditFormFromQuery />)
    expect(await screen.findByDisplayValue('Front')).toBeTruthy()

    fireEvent.change(labelInput(), { target: { value: 'Back door' } })
    served.code = makeCode({ label: 'Garage' })
    await queryClient.invalidateQueries()
    expect(await screen.findByText(NOTICE)).toBeTruthy()

    fireEvent.change(labelInput(), { target: { value: 'Garage' } })
    expect(screen.queryByText(NOTICE)).toBeNull()
  })
})
