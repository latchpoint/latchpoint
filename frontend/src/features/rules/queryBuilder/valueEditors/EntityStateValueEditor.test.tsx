import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render } from '@testing-library/react'

import { EntityStateValueEditor } from './EntityStateValueEditor'
import type { EntityOption, EntityStateValue, ValueEditorContext } from '../types'

function makeEntityOption(entityId: string, domain: string): EntityOption {
  return { entityId, name: entityId, domain, source: 'home_assistant' }
}

function renderEditor({
  value,
  entities,
  handleOnChange = () => {},
}: {
  value: EntityStateValue
  entities: EntityOption[]
  handleOnChange?: (v: EntityStateValue) => void
}) {
  const context: ValueEditorContext = { entities }
  // EntityStateValueEditor extends react-querybuilder's ValueEditorProps but
  // only reads a handful of fields. The cast keeps the unit test narrow
  // instead of reconstructing the full react-querybuilder prop surface.
  const props = {
    value,
    handleOnChange,
    disabled: false,
    context,
  } as unknown as React.ComponentProps<typeof EntityStateValueEditor>
  return render(<EntityStateValueEditor {...props} />)
}

function getEqualsInput(container: HTMLElement): HTMLInputElement {
  const input = container.querySelector<HTMLInputElement>('input[placeholder="on"]')
  if (!input) throw new Error('equals input not found')
  return input
}

function getDatalistOptions(container: HTMLElement): string[] {
  const listId = getEqualsInput(container).getAttribute('list')
  if (!listId) throw new Error('equals input is missing its list attribute')
  const list = container.ownerDocument.getElementById(listId)
  if (!list) throw new Error(`datalist #${listId} not found`)
  return Array.from(list.querySelectorAll('option')).map((o) => o.getAttribute('value') ?? '')
}

describe('EntityStateValueEditor', () => {
  it('offers canonical on/off suggestions for a binary_sensor entity', () => {
    const { container } = renderEditor({
      value: { entityId: 'binary_sensor.front_door', equals: 'on' },
      entities: [makeEntityOption('binary_sensor.front_door', 'binary_sensor')],
    })
    expect(getDatalistOptions(container)).toEqual(['on', 'off'])
  })

  it('offers the full lock state vocabulary for a lock entity', () => {
    const { container } = renderEditor({
      value: { entityId: 'lock.front_door', equals: 'locked' },
      entities: [makeEntityOption('lock.front_door', 'lock')],
    })
    expect(getDatalistOptions(container)).toEqual([
      'locked',
      'unlocked',
      'locking',
      'unlocking',
      'jammed',
      'unknown',
    ])
  })

  it('renders no suggestions for sensor — arbitrary values remain valid', () => {
    const handleOnChange = vi.fn()
    const { container } = renderEditor({
      value: { entityId: 'sensor.temp_kitchen', equals: '' },
      entities: [makeEntityOption('sensor.temp_kitchen', 'sensor')],
      handleOnChange,
    })
    expect(getDatalistOptions(container)).toEqual([])

    fireEvent.change(getEqualsInput(container), { target: { value: '27.5' } })
    expect(handleOnChange).toHaveBeenCalledWith({
      entityId: 'sensor.temp_kitchen',
      equals: '27.5',
    })
  })

  it('forwards typed custom values via handleOnChange', () => {
    const handleOnChange = vi.fn()
    const { container } = renderEditor({
      value: { entityId: 'climate.living_room', equals: 'off' },
      entities: [makeEntityOption('climate.living_room', 'climate')],
      handleOnChange,
    })
    const input = getEqualsInput(container)

    fireEvent.change(input, { target: { value: 'heat_cool' } })
    expect(handleOnChange).toHaveBeenLastCalledWith({
      entityId: 'climate.living_room',
      equals: 'heat_cool',
    })

    fireEvent.change(input, { target: { value: 'a_totally_custom_mode' } })
    expect(handleOnChange).toHaveBeenLastCalledWith({
      entityId: 'climate.living_room',
      equals: 'a_totally_custom_mode',
    })
  })

  it('loads pre-existing rules with uncommon equals values unchanged', () => {
    const { container } = renderEditor({
      value: { entityId: 'cover.garage', equals: 'some_weird_custom_state' },
      entities: [makeEntityOption('cover.garage', 'cover')],
    })
    const input = getEqualsInput(container)
    expect(input.value).toBe('some_weird_custom_state')
    expect(getDatalistOptions(container)).toEqual([
      'open',
      'closed',
      'opening',
      'closing',
      'stopped',
    ])
  })
})
