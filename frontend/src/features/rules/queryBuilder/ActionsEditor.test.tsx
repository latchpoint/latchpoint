import React from 'react'
import { describe, expect, it, vi } from 'vitest'
import { fireEvent, screen } from '@testing-library/react'
import { renderWithProviders } from '@/test/render'
import type { ActionNode } from '@/types/ruleDefinition'
import type { Entity } from '@/types/rules'

// Stub the integration-status hooks ActionsEditor uses to gate which action
// types are available. We want HA enabled (so ha_call_service is available)
// and the others disabled (kept off the picker so tests stay focused).
vi.mock('@/hooks/useHomeAssistant', () => ({
  useHomeAssistantStatus: () => ({ data: { configured: true } }),
  useHomeAssistantNotifyServices: () => ({ data: [] }),
}))
vi.mock('@/hooks/useZwavejs', () => ({
  useZwavejsStatusQuery: () => ({ data: { configured: false, enabled: false } }),
}))
vi.mock('@/hooks/useZigbee2mqtt', () => ({
  useZigbee2mqttStatusQuery: () => ({ data: { enabled: false } }),
}))
vi.mock('@/features/notifications/hooks/useNotificationProviders', () => ({
  useEnabledNotificationProviders: () => ({ data: [] }),
}))

function makeEntity(entityId: string, source = 'home_assistant'): Entity {
  return {
    id: 1,
    entityId,
    name: entityId,
    domain: entityId.split('.')[0] ?? '',
    deviceClass: null,
    lastState: null,
    lastChanged: null,
    lastSeen: null,
    attributes: {},
    source,
    createdAt: '2026-01-01T00:00:00Z',
    updatedAt: '2026-01-01T00:00:00Z',
  }
}

function makeCallServiceAction(entityIds: string[] = []): ActionNode {
  return {
    type: 'ha_call_service',
    action: 'light.turn_on',
    target: { entityIds },
    data: {},
  }
}

describe('ActionsEditor', () => {
  it('imports', async () => {
    const mod = await import('./ActionsEditor')
    expect(mod).toBeTruthy()
  })

  it('shows the empty-state hint and an Add entity button for a fresh ha_call_service', async () => {
    const { ActionsEditor } = await import('./ActionsEditor')
    renderWithProviders(
      <ActionsEditor
        actions={[makeCallServiceAction([])]}
        onChange={vi.fn()}
        entities={[makeEntity('light.kitchen')]}
      />
    )

    expect(screen.getByText(/no entities targeted yet/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /\+ add entity/i })).toBeInTheDocument()
  })

  it('appends an empty entity-id slot when Add entity is clicked', async () => {
    const { ActionsEditor } = await import('./ActionsEditor')
    const onChange = vi.fn()
    renderWithProviders(
      <ActionsEditor
        actions={[makeCallServiceAction([])]}
        onChange={onChange}
        entities={[makeEntity('light.kitchen')]}
      />
    )

    fireEvent.click(screen.getByRole('button', { name: /\+ add entity/i }))
    expect(onChange).toHaveBeenCalledWith([
      expect.objectContaining({
        type: 'ha_call_service',
        target: { entityIds: [''] },
      }),
    ])
  })

  it('emits the picked entity id when an entity is selected from the dropdown', async () => {
    const { ActionsEditor } = await import('./ActionsEditor')
    const onChange = vi.fn()
    renderWithProviders(
      <ActionsEditor
        actions={[makeCallServiceAction([''])]}
        onChange={onChange}
        entities={[makeEntity('light.kitchen')]}
      />
    )

    // The picker's trigger button shows the placeholder; click it to open the
    // dropdown, then click the entity row to select it.
    fireEvent.click(screen.getByText(/^select entity\.\.\.$/i))
    fireEvent.click(screen.getByText('light.kitchen'))

    expect(onChange).toHaveBeenCalledWith([
      expect.objectContaining({
        type: 'ha_call_service',
        target: { entityIds: ['light.kitchen'] },
      }),
    ])
  })

  it('drops the row from the array when the row trash button is clicked', async () => {
    const { ActionsEditor } = await import('./ActionsEditor')
    const onChange = vi.fn()
    renderWithProviders(
      <ActionsEditor
        actions={[makeCallServiceAction(['light.kitchen', 'switch.garage'])]}
        onChange={onChange}
        entities={[makeEntity('light.kitchen'), makeEntity('switch.garage')]}
      />
    )

    const removeButtons = screen.getAllByRole('button', { name: /remove entity/i })
    expect(removeButtons).toHaveLength(2)
    fireEvent.click(removeButtons[0])

    expect(onChange).toHaveBeenCalledWith([
      expect.objectContaining({
        type: 'ha_call_service',
        target: { entityIds: ['switch.garage'] },
      }),
    ])
  })

  it('hides non-home_assistant entities from the picker dropdown', async () => {
    const { ActionsEditor } = await import('./ActionsEditor')
    renderWithProviders(
      <ActionsEditor
        actions={[makeCallServiceAction([''])]}
        onChange={vi.fn()}
        entities={[
          makeEntity('light.kitchen', 'home_assistant'),
          makeEntity('zwave.dimmer', 'zwavejs'),
        ]}
      />
    )

    fireEvent.click(screen.getByText(/^select entity\.\.\.$/i))
    expect(screen.getByText('light.kitchen')).toBeInTheDocument()
    expect(screen.queryByText('zwave.dimmer')).toBeNull()
  })

  // ── alarm_trigger (ADR-0094 §9 decision (a): no delay, no fields) ────────

  it('renders alarm_trigger as a single row with no expandable details', async () => {
    const { ActionsEditor } = await import('./ActionsEditor')
    renderWithProviders(
      <ActionsEditor
        actions={[{ type: 'alarm_trigger' }]}
        onChange={vi.fn()}
        entities={[]}
      />
    )
    // No "Entry delay" panel anymore — alarm_trigger has no params under
    // decision (a). To compose a delayed trigger, the author writes
    // [alarm_set_state(pending), alarm_set_state(triggered, delaySeconds: N)].
    expect(screen.queryByText(/entry delay/i)).toBeNull()
    // The action row itself is still rendered (selector dropdown).
    expect(screen.getByRole('combobox')).toBeInTheDocument()
  })

  // ── send_notification delay (ADR-0091) ───────────────────────────────────

  it('shows a "delay Ns" badge for send_notification with a non-zero delaySeconds', async () => {
    const { ActionsEditor } = await import('./ActionsEditor')
    renderWithProviders(
      <ActionsEditor
        actions={[
          {
            type: 'send_notification',
            providerId: 'home_assistant',
            message: 'hi',
            delaySeconds: 30,
          },
        ]}
        onChange={vi.fn()}
        entities={[]}
      />
    )
    expect(screen.getByText(/^delay 30s$/i)).toBeInTheDocument()
  })

  it('emits delaySeconds when the user types a positive value into the send_notification delay input', async () => {
    const { ActionsEditor } = await import('./ActionsEditor')
    const onChange = vi.fn()
    renderWithProviders(
      <ActionsEditor
        actions={[
          {
            type: 'send_notification',
            providerId: 'home_assistant',
            message: 'hi',
          },
        ]}
        onChange={onChange}
        entities={[]}
      />
    )
    const input = screen.getByPlaceholderText(/send immediately/i)
    fireEvent.change(input, { target: { value: '45' } })
    expect(onChange).toHaveBeenLastCalledWith([
      expect.objectContaining({
        type: 'send_notification',
        providerId: 'home_assistant',
        message: 'hi',
        delaySeconds: 45,
      }),
    ])
  })

  it('strips delaySeconds when the user clears the send_notification delay input', async () => {
    const { ActionsEditor } = await import('./ActionsEditor')
    const onChange = vi.fn()
    renderWithProviders(
      <ActionsEditor
        actions={[
          {
            type: 'send_notification',
            providerId: 'home_assistant',
            message: 'hi',
            delaySeconds: 30,
          },
        ]}
        onChange={onChange}
        entities={[]}
      />
    )
    const input = screen.getByPlaceholderText(/send immediately/i)
    fireEvent.change(input, { target: { value: '' } })
    const lastCall = onChange.mock.calls.at(-1)?.[0] as Array<Record<string, unknown>>
    expect(lastCall[0]).toEqual({
      type: 'send_notification',
      providerId: 'home_assistant',
      message: 'hi',
    })
  })

  it('rejects send_notification delaySeconds above 600 with an inline error', async () => {
    const { ActionsEditor } = await import('./ActionsEditor')
    const onChange = vi.fn()
    renderWithProviders(
      <ActionsEditor
        actions={[
          {
            type: 'send_notification',
            providerId: 'home_assistant',
            message: 'hi',
            delaySeconds: 30,
          },
        ]}
        onChange={onChange}
        entities={[]}
      />
    )
    onChange.mockClear()
    const input = screen.getByPlaceholderText(/send immediately/i)
    fireEvent.change(input, { target: { value: '900' } })
    expect(screen.getByText(/must be ≤ 600 seconds/i)).toBeInTheDocument()
    expect(onChange).not.toHaveBeenCalled()
  })
})
