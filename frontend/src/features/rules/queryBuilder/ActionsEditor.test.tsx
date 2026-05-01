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
})
