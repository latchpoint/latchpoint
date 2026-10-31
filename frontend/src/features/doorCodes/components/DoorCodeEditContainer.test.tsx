import { StrictMode } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { act, fireEvent, screen, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { server } from '@/test/msw/server'
import { renderWithProviders } from '@/test/render'
import { DOOR_CODES_SETTLING_POLL_MS, useDoorCodesQuery } from '@/hooks/useDoorCodesQueries'
import { DoorCodeEditContainer } from './DoorCodeEditContainer'
import type { DoorCode, Entity, UpdateDoorCodeRequest } from '@/types'

const PAGE_USER_ID = 'selected-user'
const KEPT = 'Your unsaved changes are kept.'

function makeCode(overrides: Partial<DoorCode> = {}): DoorCode {
  return {
    id: 7,
    userId: '00000000-0000-0000-0000-000000000001',
    userDisplayName: 'Test',
    source: 'manual',
    label: 'Front',
    codeType: 'temporary',
    pin: '1357',
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
    lockSlotAssignments: [{ lockEntityId: 'lock.front_door', slotIndex: 3, pendingRemoval: false }],
    pendingSlotClears: [],
    validity: 'valid',
    pushState: 'pushed',
    lastPushError: '',
    lastPushAttemptAt: '2026-10-28T10:00:00Z',
    createdAt: '',
    updatedAt: '',
    ...overrides,
  }
}

function makeLock(entityId: string, name: string): Entity {
  return {
    id: entityId.length,
    entityId,
    domain: 'lock',
    name,
    deviceClass: null,
    lastState: 'locked',
    lastChanged: null,
    lastSeen: null,
    attributes: {},
    source: 'home_assistant',
    createdAt: '',
    updatedAt: '',
  }
}

const LOCKS = [makeLock('lock.a', 'Lock A'), makeLock('lock.b', 'Lock B'), makeLock('lock.d', 'Lock D')]

type OnUpdate = (id: number, req: UpdateDoorCodeRequest) => Promise<unknown>

// The edit form fed from the real door codes query, the way DoorCodeCard gets
// its code on the page.
function EditFormFromQuery({ onUpdate = vi.fn(), locks = [] }: { onUpdate?: OnUpdate; locks?: Entity[] }) {
  const codesQuery = useDoorCodesQuery({ userId: PAGE_USER_ID, isAdmin: true })
  const code = codesQuery.data?.[0]
  if (!code) return null
  return (
    <DoorCodeEditContainer
      code={code}
      locks={locks}
      locksIsLoading={false}
      locksError={null}
      isSaving={false}
      isDeleting={false}
      onClose={vi.fn()}
      onUpdate={onUpdate}
      onDelete={vi.fn()}
    />
  )
}

// Serves state.code from the codes endpoint and counts the fetches. Tests
// change it, then refetch.
function serveCode(initial: DoorCode) {
  const state = { code: initial, fetches: 0 }
  server.use(
    http.get('/api/door-codes/', () => {
      state.fetches += 1
      return HttpResponse.json({ data: [state.code] })
    }),
  )
  return state
}

function renderForm(initial: DoorCode, props: { onUpdate?: OnUpdate; locks?: Entity[] } = {}) {
  const served = serveCode(initial)
  const { queryClient } = renderWithProviders(<EditFormFromQuery {...props} />)
  const serverChanges = async (next: DoorCode) => {
    served.code = next
    await queryClient.invalidateQueries()
  }
  return { serverChanges }
}

const labelInput = () => screen.getByLabelText('Label') as HTMLInputElement
const newCodeInput = () => screen.getByLabelText('New code (optional)') as HTMLInputElement
const windowStartInput = () => screen.getByLabelText('Time window start (optional)') as HTMLInputElement
const windowEndInput = () => screen.getByLabelText('Time window end (optional)') as HTMLInputElement
const dayCheckbox = (day: string) => screen.getByRole('checkbox', { name: day })
const lockCheckbox = (entityId: string) => screen.getByRole('checkbox', { name: new RegExp(`\\(${entityId}\\)`) })
const activeSwitch = () => screen.getByRole('switch', { name: 'Active' })
const notice = () => screen.getByRole('status')

function save() {
  fireEvent.change(screen.getByLabelText(/Re-authenticate/), { target: { value: 'pw' } })
  fireEvent.click(screen.getByRole('button', { name: 'Save' }))
}

async function savedRequest(onUpdate: ReturnType<typeof vi.fn>): Promise<UpdateDoorCodeRequest> {
  save()
  await waitFor(() => expect(onUpdate).toHaveBeenCalledTimes(1))
  return onUpdate.mock.calls[0][1] as UpdateDoorCodeRequest
}

describe('DoorCodeEditContainer', () => {
  it('imports', async () => {
    const mod = await import('./DoorCodeEditContainer')
    expect(mod).toBeTruthy()
  })

  describe('refetches', () => {
    afterEach(() => {
      vi.useRealTimers()
    })

    it('keeps an edit in progress across polls while the code is pending', async () => {
      vi.useFakeTimers({ shouldAdvanceTime: true })
      const nextPoll = () => act(() => vi.advanceTimersByTimeAsync(DOOR_CODES_SETTLING_POLL_MS))
      // Its lock has no slot yet, so the scheduler is still pushing it.
      const served = serveCode(
        makeCode({
          pushState: 'pending',
          lockSlotAssignments: [{ lockEntityId: 'lock.front_door', slotIndex: null, pendingRemoval: false }],
        }),
      )
      renderWithProviders(<EditFormFromQuery />)
      expect(await screen.findByDisplayValue('Front')).toBeTruthy()
      expect(served.fetches).toBe(1)

      fireEvent.change(labelInput(), { target: { value: 'Back door' } })
      fireEvent.change(newCodeInput(), { target: { value: '2468' } })
      fireEvent.click(dayCheckbox('Sun'))
      fireEvent.change(screen.getByLabelText(/Re-authenticate/), { target: { value: 'pw' } })

      // A poll with nothing new.
      await nextPoll()
      await waitFor(() => expect(served.fetches).toBe(2))
      expect(labelInput().value).toBe('Back door')
      expect(newCodeInput().value).toBe('2468')
      expect(dayCheckbox('Sun')).not.toBeChecked()

      // The scheduler pushes it, and another tab changes the time window.
      served.code = makeCode({ windowEnd: '18:00', lastPushAttemptAt: '2026-10-28T10:05:00Z' })
      await nextPoll()
      await waitFor(() => expect(served.fetches).toBe(3))
      await waitFor(() => expect(windowEndInput().value).toBe('18:00'))

      expect(labelInput().value).toBe('Back door')
      expect(newCodeInput().value).toBe('2468')
      expect(dayCheckbox('Sun')).not.toBeChecked()
      expect((screen.getByLabelText(/Re-authenticate/) as HTMLInputElement).value).toBe('pw')
      expect(notice()).toBeEmptyDOMElement()
    })

    it('keeps an edit in progress when the code changes on the server', async () => {
      const { serverChanges } = renderForm(makeCode())
      expect(await screen.findByDisplayValue('Front')).toBeTruthy()

      fireEvent.change(labelInput(), { target: { value: 'Back door' } })
      fireEvent.change(newCodeInput(), { target: { value: '2468' } })
      fireEvent.click(dayCheckbox('Sun'))

      // The scheduler retries the push and something else on the code changes.
      await serverChanges(makeCode({ windowEnd: '18:00', lastPushAttemptAt: '2026-10-28T10:05:00Z' }))
      await waitFor(() => expect(windowEndInput().value).toBe('18:00'))

      expect(labelInput().value).toBe('Back door')
      expect(newCodeInput().value).toBe('2468')
      expect(dayCheckbox('Sun')).not.toBeChecked()
      expect(notice()).toHaveTextContent('')
    })

    it("updates the fields the user hasn't edited", async () => {
      const { serverChanges } = renderForm(makeCode())
      expect(await screen.findByDisplayValue('Front')).toBeTruthy()
      expect(activeSwitch()).toHaveAttribute('aria-checked', 'true')

      fireEvent.change(labelInput(), { target: { value: 'Back door' } })

      // A refused delete in another tab turns the code off.
      await serverChanges(makeCode({ isActive: false, windowStart: '07:00', windowEnd: '18:00', pushState: 'pending' }))

      await waitFor(() => expect(activeSwitch()).toHaveAttribute('aria-checked', 'false'))
      expect(windowStartInput().value).toBe('07:00')
      expect(windowEndInput().value).toBe('18:00')
      expect(labelInput().value).toBe('Back door')
    })

    it('keeps the status region in the page and fills it in on a conflict', async () => {
      const { serverChanges } = renderForm(makeCode())
      expect(await screen.findByDisplayValue('Front')).toBeTruthy()
      const region = notice()
      expect(region).toBeEmptyDOMElement()

      fireEvent.change(labelInput(), { target: { value: 'Back door' } })
      await serverChanges(makeCode({ label: 'Garage' }))

      await waitFor(() => expect(region).toHaveTextContent(`Label changed on the server. ${KEPT}`))
      expect(notice()).toBe(region)
      expect(labelInput().value).toBe('Back door')
    })

    it('names every field that conflicted', async () => {
      const { serverChanges } = renderForm(makeCode())
      expect(await screen.findByDisplayValue('Front')).toBeTruthy()

      fireEvent.change(labelInput(), { target: { value: 'Back door' } })
      fireEvent.change(windowEndInput(), { target: { value: '19:00' } })
      await serverChanges(makeCode({ label: 'Garage', windowEnd: '18:00' }))

      await waitFor(() => expect(notice()).toHaveTextContent(`Label and Time window changed on the server. ${KEPT}`))
      expect(labelInput().value).toBe('Back door')
      expect(windowEndInput().value).toBe('19:00')
    })

    it('puts the form back to the server values on discard', async () => {
      const { serverChanges } = renderForm(makeCode())
      expect(await screen.findByDisplayValue('Front')).toBeTruthy()

      fireEvent.change(labelInput(), { target: { value: 'Back door' } })
      fireEvent.change(newCodeInput(), { target: { value: '2468' } })
      fireEvent.click(dayCheckbox('Sun'))

      await serverChanges(makeCode({ label: 'Garage', windowEnd: '18:00' }))
      await waitFor(() => expect(notice()).toHaveTextContent(KEPT))

      fireEvent.click(screen.getByRole('button', { name: 'Discard changes and reload' }))

      expect(labelInput().value).toBe('Garage')
      expect(newCodeInput().value).toBe('')
      expect(dayCheckbox('Sun')).toBeChecked()
      expect(windowEndInput().value).toBe('18:00')
      expect(notice()).toBeEmptyDOMElement()

      // With nothing edited the form follows the server again.
      await serverChanges(makeCode({ label: 'Side gate', windowEnd: '18:00' }))
      await waitFor(() => expect(labelInput().value).toBe('Side gate'))
      expect(notice()).toBeEmptyDOMElement()
    })

    it('drops the notice once the edit matches the server', async () => {
      const { serverChanges } = renderForm(makeCode())
      expect(await screen.findByDisplayValue('Front')).toBeTruthy()

      fireEvent.change(labelInput(), { target: { value: 'Back door' } })
      await serverChanges(makeCode({ label: 'Garage' }))
      await waitFor(() => expect(notice()).toHaveTextContent(KEPT))

      fireEvent.change(labelInput(), { target: { value: 'Garage' } })
      expect(notice()).toBeEmptyDOMElement()
    })
  })

  describe('locks', () => {
    const withLocks = (ids: string[]) =>
      makeCode({ lockEntityIds: ids, lockAssignments: ids.map((id, i) => ({ id: i + 1, lockEntityId: id })) })

    it("doesn't add back a lock the server dropped while another lock was being added", async () => {
      const onUpdate = vi.fn().mockResolvedValue(undefined)
      // Lock B's drop is still waiting on its clear, so it's still listed.
      const { serverChanges } = renderForm(withLocks(['lock.a', 'lock.b']), { onUpdate, locks: LOCKS })
      expect(await screen.findByDisplayValue('Front')).toBeTruthy()
      expect(lockCheckbox('lock.b')).toBeChecked()

      fireEvent.click(lockCheckbox('lock.d'))

      // The clear lands and the refetch only has lock A.
      await serverChanges(withLocks(['lock.a']))
      await waitFor(() => expect(lockCheckbox('lock.b')).not.toBeChecked())
      expect(lockCheckbox('lock.a')).toBeChecked()
      expect(lockCheckbox('lock.d')).toBeChecked()
      expect(notice()).toBeEmptyDOMElement()

      // Only the user's change goes out (#159).
      const req = await savedRequest(onUpdate)
      expect(req).toEqual({ reauthPassword: 'pw', addLockEntityIds: ['lock.d'] })
    })

    it("sends only the user's lock changes, not the locks this tab last fetched", async () => {
      // #159: another tab removed lock B and this tab never refetched, so it
      // still shows A and B. Sending its whole set would put B back.
      const onUpdate = vi.fn().mockResolvedValue(undefined)
      renderForm(withLocks(['lock.a', 'lock.b']), { onUpdate, locks: LOCKS })
      expect(await screen.findByDisplayValue('Front')).toBeTruthy()

      fireEvent.click(lockCheckbox('lock.d'))
      fireEvent.click(lockCheckbox('lock.a'))

      const req = await savedRequest(onUpdate)
      expect(req).toEqual({
        reauthPassword: 'pw',
        addLockEntityIds: ['lock.d'],
        removeLockEntityIds: ['lock.a'],
      })
      expect(req).not.toHaveProperty('lockEntityIds')
    })

    // #151: Lock B was unticked and saved, but its slot clear failed, so it's still
    // on the code with pendingRemoval until the clear works. Older APIs also
    // listed it in lockEntityIds, which the form has to handle the same (#171).
    const withBRemoving = () =>
      makeCode({
        lockEntityIds: ['lock.a', 'lock.b'],
        lockAssignments: [
          { id: 1, lockEntityId: 'lock.a' },
          { id: 2, lockEntityId: 'lock.b' },
        ],
        lockSlotAssignments: [
          { lockEntityId: 'lock.a', slotIndex: 1, pendingRemoval: false },
          { lockEntityId: 'lock.b', slotIndex: 1, pendingRemoval: true },
        ],
        pendingSlotClears: [{ lockEntityId: 'lock.b', slotIndex: 1, removing: true }],
      })

    it("doesn't cancel a pending removal when another lock is added", async () => {
      const onUpdate = vi.fn().mockResolvedValue(undefined)
      renderForm(withBRemoving(), { onUpdate, locks: LOCKS })
      expect(await screen.findByDisplayValue('Front')).toBeTruthy()
      expect(lockCheckbox('lock.a')).toBeChecked()
      expect(lockCheckbox('lock.b')).not.toBeChecked()

      fireEvent.click(lockCheckbox('lock.d'))

      // Sending lock B again would keep it on the code.
      const req = await savedRequest(onUpdate)
      expect(req).toEqual({ reauthPassword: 'pw', addLockEntityIds: ['lock.d'] })
    })

    it('treats a lock being removed the same when the API leaves it out of lockEntityIds (#171)', async () => {
      const onUpdate = vi.fn().mockResolvedValue(undefined)
      renderForm({ ...withBRemoving(), lockEntityIds: ['lock.a'] }, { onUpdate, locks: LOCKS })
      expect(await screen.findByDisplayValue('Front')).toBeTruthy()
      expect(lockCheckbox('lock.a')).toBeChecked()
      expect(lockCheckbox('lock.b')).not.toBeChecked()

      fireEvent.click(lockCheckbox('lock.b'))

      const req = await savedRequest(onUpdate)
      expect(req).toEqual({ reauthPassword: 'pw', addLockEntityIds: ['lock.b'] })
    })

    it("doesn't send the locks at all when only another field was edited", async () => {
      const onUpdate = vi.fn().mockResolvedValue(undefined)
      renderForm(withBRemoving(), { onUpdate, locks: LOCKS })
      expect(await screen.findByDisplayValue('Front')).toBeTruthy()

      fireEvent.change(labelInput(), { target: { value: 'Back door' } })

      expect(await savedRequest(onUpdate)).toEqual({ reauthPassword: 'pw', label: 'Back door' })
    })

    it('cancels a pending removal only when the user ticks the lock again', async () => {
      const onUpdate = vi.fn().mockResolvedValue(undefined)
      renderForm(withBRemoving(), { onUpdate, locks: LOCKS })
      expect(await screen.findByDisplayValue('Front')).toBeTruthy()

      fireEvent.click(lockCheckbox('lock.b'))

      const req = await savedRequest(onUpdate)
      expect(req).toEqual({ reauthPassword: 'pw', addLockEntityIds: ['lock.b'] })
    })

    it('leaves the removed lock off once its clear works', async () => {
      const onUpdate = vi.fn().mockResolvedValue(undefined)
      const { serverChanges } = renderForm(withBRemoving(), { onUpdate, locks: LOCKS })
      expect(await screen.findByDisplayValue('Front')).toBeTruthy()

      fireEvent.click(lockCheckbox('lock.d'))
      await serverChanges(withLocks(['lock.a']))

      await waitFor(() => expect(lockCheckbox('lock.d')).toBeChecked())
      expect(lockCheckbox('lock.b')).not.toBeChecked()
      expect(notice()).toBeEmptyDOMElement()
      const req = await savedRequest(onUpdate)
      expect(req).toEqual({ reauthPassword: 'pw', addLockEntityIds: ['lock.d'] })
    })

    it('keeps a lock the user removed off when the server adds a different one', async () => {
      const onUpdate = vi.fn().mockResolvedValue(undefined)
      const { serverChanges } = renderForm(withLocks(['lock.a', 'lock.b']), { onUpdate, locks: LOCKS })
      expect(await screen.findByDisplayValue('Front')).toBeTruthy()

      fireEvent.click(lockCheckbox('lock.a'))
      await serverChanges(withLocks(['lock.a', 'lock.b', 'lock.d']))

      await waitFor(() => expect(lockCheckbox('lock.d')).toBeChecked())
      expect(lockCheckbox('lock.a')).not.toBeChecked()
      expect(lockCheckbox('lock.b')).toBeChecked()

      // The server's new lock D isn't sent back, only the user's removal of A.
      const req = await savedRequest(onUpdate)
      expect(req).toEqual({ reauthPassword: 'pw', removeLockEntityIds: ['lock.a'] })
    })
  })

  describe('schedule', () => {
    it('merges the days the user and the server each changed', async () => {
      const onUpdate = vi.fn().mockResolvedValue(undefined)
      const { serverChanges } = renderForm(makeCode(), { onUpdate })
      expect(await screen.findByDisplayValue('Front')).toBeTruthy()

      fireEvent.click(dayCheckbox('Sun'))
      // The server turns Saturday off.
      await serverChanges(makeCode({ daysOfWeek: 127 & ~(1 << 5) }))

      await waitFor(() => expect(dayCheckbox('Sat')).not.toBeChecked())
      expect(dayCheckbox('Sun')).not.toBeChecked()
      expect(dayCheckbox('Fri')).toBeChecked()
      expect(notice()).toBeEmptyDOMElement()

      const req = await savedRequest(onUpdate)
      expect(req.daysOfWeek).toBe(0b0011111)
    })

    it("keeps the user's whole time window when the server changes the other end", async () => {
      const onUpdate = vi.fn().mockResolvedValue(undefined)
      const { serverChanges } = renderForm(makeCode(), { onUpdate })
      expect(await screen.findByDisplayValue('Front')).toBeTruthy()

      fireEvent.change(windowStartInput(), { target: { value: '09:00' } })
      await serverChanges(makeCode({ windowEnd: '18:00' }))

      await waitFor(() => expect(notice()).toHaveTextContent(`Time window changed on the server. ${KEPT}`))
      expect(windowStartInput().value).toBe('09:00')
      expect(windowEndInput().value).toBe('17:00')

      const req = await savedRequest(onUpdate)
      expect(req).toMatchObject({ windowStart: '09:00', windowEnd: '17:00' })
    })

    it("keeps the user's date range when the server changes it", async () => {
      const onUpdate = vi.fn().mockResolvedValue(undefined)
      const ranged = (endAt: string) => makeCode({ startAt: '2026-11-01T12:00:00Z', endAt })
      const { serverChanges } = renderForm(ranged('2026-11-05T12:00:00Z'), { onUpdate })
      expect(await screen.findByDisplayValue('Front')).toBeTruthy()

      // Clear the range in the picker.
      fireEvent.click(screen.getByRole('button', { name: /→/ }))
      fireEvent.click(screen.getByRole('button', { name: 'Clear' }))
      fireEvent.click(screen.getByRole('button', { name: 'Done' }))
      expect(screen.getByText('Select date range…')).toBeTruthy()

      await serverChanges(ranged('2026-11-09T12:00:00Z'))
      await waitFor(() => expect(notice()).toHaveTextContent(`Active date range changed on the server. ${KEPT}`))
      expect(screen.getByText('Select date range…')).toBeTruthy()

      const req = await savedRequest(onUpdate)
      expect(req).toMatchObject({ startAt: null, endAt: null })
    })
  })

  it('flags a typed new PIN when the PIN changed on the server', async () => {
    const onUpdate = vi.fn().mockResolvedValue(undefined)
    const { serverChanges } = renderForm(makeCode(), { onUpdate })
    expect(await screen.findByDisplayValue('Front')).toBeTruthy()

    fireEvent.change(newCodeInput(), { target: { value: '2468' } })
    await serverChanges(makeCode({ pin: '97531', pinLength: 5 }))

    await waitFor(() => expect(notice()).toHaveTextContent(`New code changed on the server. ${KEPT}`))
    expect(newCodeInput().value).toBe('2468')

    const req = await savedRequest(onUpdate)
    expect(req.code).toBe('2468')
  })

  it("doesn't bring the PIN notice back once the server's PIN was typed", async () => {
    const { serverChanges } = renderForm(makeCode())
    expect(await screen.findByDisplayValue('Front')).toBeTruthy()

    fireEvent.change(newCodeInput(), { target: { value: '2468' } })
    await serverChanges(makeCode({ pin: '97531', pinLength: 5 }))
    await waitFor(() => expect(notice()).toHaveTextContent(`New code changed on the server. ${KEPT}`))

    fireEvent.change(newCodeInput(), { target: { value: '97531' } })
    expect(notice()).toBeEmptyDOMElement()

    // The server hasn't changed again, so another PIN is just an edit.
    fireEvent.change(newCodeInput(), { target: { value: '1111' } })
    expect(notice()).toBeEmptyDOMElement()
  })

  describe('saving', () => {
    it('sends only the password when nothing was edited on an active code', async () => {
      const onUpdate = vi.fn().mockResolvedValue(undefined)
      renderForm(makeCode(), { onUpdate })
      expect(await screen.findByDisplayValue('Front')).toBeTruthy()

      const req = await savedRequest(onUpdate)
      expect(req).toEqual({ reauthPassword: 'pw' })
      expect(req).not.toHaveProperty('isActive')
    })

    it('always sends off for an inactive code so the save can clear its PIN from the lock', async () => {
      const onUpdate = vi.fn().mockResolvedValue(undefined)
      renderForm(makeCode({ isActive: false }), { onUpdate })
      expect(await screen.findByDisplayValue('Front')).toBeTruthy()
      expect(activeSwitch()).toHaveAttribute('aria-checked', 'false')

      expect(await savedRequest(onUpdate)).toEqual({ reauthPassword: 'pw', isActive: false })
    })

    it('sends only the edited fields, even when they conflicted', async () => {
      const onUpdate = vi.fn().mockResolvedValue(undefined)
      const { serverChanges } = renderForm(makeCode(), { onUpdate })
      expect(await screen.findByDisplayValue('Front')).toBeTruthy()

      fireEvent.change(labelInput(), { target: { value: 'Back door' } })
      // Turned off elsewhere, along with a label change. Off is always sent.
      await serverChanges(makeCode({ label: 'Garage', isActive: false }))
      await waitFor(() => expect(notice()).toHaveTextContent(KEPT))

      expect(await savedRequest(onUpdate)).toEqual({ reauthPassword: 'pw', label: 'Back door', isActive: false })
    })

    it("doesn't send the active state from a tab that never saw it change", async () => {
      const onUpdate = vi.fn().mockResolvedValue(undefined)
      renderForm(makeCode(), { onUpdate })
      expect(await screen.findByDisplayValue('Front')).toBeTruthy()

      // This tab still shows the code on. It may have been turned off elsewhere.
      fireEvent.change(labelInput(), { target: { value: 'Back door' } })

      const req = await savedRequest(onUpdate)
      expect(req).toEqual({ reauthPassword: 'pw', label: 'Back door' })
      expect(req).not.toHaveProperty('isActive')
    })
  })

  it('merges and flags the same way under StrictMode', async () => {
    const onUpdate = vi.fn().mockResolvedValue(undefined)
    const withLocks = (ids: string[], overrides: Partial<DoorCode> = {}) =>
      makeCode({ lockEntityIds: ids, ...overrides })
    const served = serveCode(withLocks(['lock.a', 'lock.b']))
    const { queryClient } = renderWithProviders(
      <StrictMode>
        <EditFormFromQuery onUpdate={onUpdate} locks={LOCKS} />
      </StrictMode>,
    )
    expect(await screen.findByDisplayValue('Front')).toBeTruthy()

    fireEvent.change(labelInput(), { target: { value: 'Back door' } })
    fireEvent.click(lockCheckbox('lock.d'))

    served.code = withLocks(['lock.a'], { windowEnd: '18:00' })
    await queryClient.invalidateQueries()
    await waitFor(() => expect(windowEndInput().value).toBe('18:00'))
    expect(labelInput().value).toBe('Back door')
    expect(lockCheckbox('lock.b')).not.toBeChecked()
    expect(lockCheckbox('lock.d')).toBeChecked()
    expect(notice()).toBeEmptyDOMElement()

    served.code = withLocks(['lock.a'], { windowEnd: '18:00', label: 'Garage' })
    await queryClient.invalidateQueries()
    await waitFor(() => expect(notice()).toHaveTextContent(`Label changed on the server. ${KEPT}`))

    const req = await savedRequest(onUpdate)
    expect(req).toEqual({
      reauthPassword: 'pw',
      label: 'Back door',
      addLockEntityIds: ['lock.d'],
    })
  })
})
