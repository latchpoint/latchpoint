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

  // ── alarm_trigger entry-delay (ADR-0091) ─────────────────────────────────

  it('shows a "delay Ns" badge for alarm_trigger with a non-zero delaySeconds', async () => {
    const { ActionsEditor } = await import('./ActionsEditor')
    renderWithProviders(
      <ActionsEditor
        actions={[{ type: 'alarm_trigger', delaySeconds: 15 }]}
        onChange={vi.fn()}
        entities={[]}
      />
    )
    expect(screen.getByText(/^delay 15s$/i)).toBeInTheDocument()
  })

  it('renders the entry-delay panel for alarm_trigger by default (no delay set)', async () => {
    const { ActionsEditor } = await import('./ActionsEditor')
    renderWithProviders(
      <ActionsEditor
        actions={[{ type: 'alarm_trigger' }]}
        onChange={vi.fn()}
        entities={[]}
      />
    )
    // Entry-delay panel is now always expanded on initial render, even with no
    // delaySeconds set — improves discoverability of the entry-delay feature.
    expect(screen.getByText(/^entry delay \(seconds\)/i)).toBeInTheDocument()
    const input = screen.getByPlaceholderText(/trigger immediately/i) as HTMLInputElement
    expect(input.value).toBe('')
  })

  it('expands the entry-delay panel when switching the action type to alarm_trigger', async () => {
    const { ActionsEditor } = await import('./ActionsEditor')
    // ActionsEditor is controlled — the test harness must apply onChange so the
    // selected action type round-trips back into the component.
    function Harness() {
      const [actions, setActions] = React.useState<ActionNode[]>([{ type: 'alarm_disarm' }])
      return <ActionsEditor actions={actions} onChange={setActions} entities={[]} />
    }
    renderWithProviders(<Harness />)
    // alarm_disarm has no expandable details, so the panel is absent.
    expect(screen.queryByText(/^entry delay \(seconds\)/i)).toBeNull()
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'alarm_trigger' } })
    expect(screen.getByText(/^entry delay \(seconds\)/i)).toBeInTheDocument()
  })

  it('emits delaySeconds when the user types a positive value', async () => {
    const { ActionsEditor } = await import('./ActionsEditor')
    const onChange = vi.fn()
    renderWithProviders(
      <ActionsEditor
        actions={[{ type: 'alarm_trigger', delaySeconds: 5 }]}
        onChange={onChange}
        entities={[]}
      />
    )
    const input = screen.getByPlaceholderText(/trigger immediately/i)
    fireEvent.change(input, { target: { value: '30' } })
    expect(onChange).toHaveBeenLastCalledWith([
      { type: 'alarm_trigger', delaySeconds: 30 },
    ])
  })

  it('strips delaySeconds when the user clears the input', async () => {
    const { ActionsEditor } = await import('./ActionsEditor')
    const onChange = vi.fn()
    renderWithProviders(
      <ActionsEditor
        actions={[{ type: 'alarm_trigger', delaySeconds: 15 }]}
        onChange={onChange}
        entities={[]}
      />
    )
    const input = screen.getByPlaceholderText(/trigger immediately/i)
    fireEvent.change(input, { target: { value: '' } })
    expect(onChange).toHaveBeenLastCalledWith([{ type: 'alarm_trigger' }])
  })

  it('strips delaySeconds when the user types 0', async () => {
    const { ActionsEditor } = await import('./ActionsEditor')
    const onChange = vi.fn()
    renderWithProviders(
      <ActionsEditor
        actions={[{ type: 'alarm_trigger', delaySeconds: 15 }]}
        onChange={onChange}
        entities={[]}
      />
    )
    const input = screen.getByPlaceholderText(/trigger immediately/i)
    fireEvent.change(input, { target: { value: '0' } })
    expect(onChange).toHaveBeenLastCalledWith([{ type: 'alarm_trigger' }])
  })

  it('rejects delaySeconds above 600 with an inline error and does not emit', async () => {
    const { ActionsEditor } = await import('./ActionsEditor')
    const onChange = vi.fn()
    renderWithProviders(
      <ActionsEditor
        actions={[{ type: 'alarm_trigger', delaySeconds: 15 }]}
        onChange={onChange}
        entities={[]}
      />
    )
    onChange.mockClear() // ignore any initial render side effects
    const input = screen.getByPlaceholderText(/trigger immediately/i)
    fireEvent.change(input, { target: { value: '700' } })
    expect(screen.getByText(/must be ≤ 600 seconds/i)).toBeInTheDocument()
    expect(onChange).not.toHaveBeenCalled()
  })

  it('rejects negative delaySeconds with an inline error and does not emit', async () => {
    const { ActionsEditor } = await import('./ActionsEditor')
    const onChange = vi.fn()
    renderWithProviders(
      <ActionsEditor
        actions={[{ type: 'alarm_trigger', delaySeconds: 15 }]}
        onChange={onChange}
        entities={[]}
      />
    )
    onChange.mockClear()
    const input = screen.getByPlaceholderText(/trigger immediately/i)
    fireEvent.change(input, { target: { value: '-5' } })
    expect(screen.getByText(/whole number/i)).toBeInTheDocument()
    expect(onChange).not.toHaveBeenCalled()
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
