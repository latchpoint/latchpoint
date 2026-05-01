import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'

import { EntityPicker } from './EntityPicker'
import type { EntityOption } from './types'

function makeEntity(entityId: string, source = 'home_assistant'): EntityOption {
  return { entityId, name: entityId, domain: entityId.split('.')[0] ?? '', source }
}

describe('EntityPicker', () => {
  it('shows the placeholder when no value is selected', () => {
    render(
      <EntityPicker
        value=""
        onChange={() => {}}
        entities={[makeEntity('light.kitchen')]}
        placeholder="Pick something"
      />
    )
    expect(screen.getByText('Pick something')).toBeTruthy()
  })

  it('opens, filters by search, and emits onChange when a row is clicked', () => {
    const onChange = vi.fn()
    const entities = [
      makeEntity('light.kitchen'),
      makeEntity('switch.garage'),
      makeEntity('lock.front_door'),
    ]
    render(<EntityPicker value="" onChange={onChange} entities={entities} />)

    // Trigger button is the only button before the dropdown opens.
    fireEvent.click(screen.getByRole('button'))

    const search = screen.getByPlaceholderText('Search entities...')
    fireEvent.change(search, { target: { value: 'kitchen' } })

    expect(screen.queryByText('light.kitchen')).toBeTruthy()
    expect(screen.queryByText('switch.garage')).toBeNull()

    fireEvent.click(screen.getByText('light.kitchen'))
    expect(onChange).toHaveBeenCalledWith('light.kitchen')
  })

  it('hides entities whose source does not match sourceFilter', () => {
    const entities = [
      makeEntity('light.kitchen', 'home_assistant'),
      makeEntity('zwave.dimmer', 'zwavejs'),
    ]
    render(
      <EntityPicker
        value=""
        onChange={() => {}}
        entities={entities}
        sourceFilter="home_assistant"
      />
    )
    fireEvent.click(screen.getByRole('button'))
    expect(screen.queryByText('light.kitchen')).toBeTruthy()
    expect(screen.queryByText('zwave.dimmer')).toBeNull()
  })

  it('does not open the dropdown when disabled', () => {
    render(
      <EntityPicker
        value=""
        onChange={() => {}}
        entities={[makeEntity('light.kitchen')]}
        disabled
      />
    )
    fireEvent.click(screen.getByRole('button'))
    expect(screen.queryByPlaceholderText('Search entities...')).toBeNull()
  })

  it('renders the selected entity id in the trigger', () => {
    render(
      <EntityPicker
        value="light.kitchen"
        onChange={() => {}}
        entities={[makeEntity('light.kitchen')]}
      />
    )
    // The truncated span on the trigger renders the matched entityId.
    expect(screen.getByRole('button').textContent).toContain('light.kitchen')
  })
})
