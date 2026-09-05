import type { ComponentProps } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, within } from '@testing-library/react'

import { EntityStateValueEditor } from './EntityStateValueEditor'
import type { EntityOption, EntitySource, EntityStateValue, ValueEditorContext } from '../types'

function makeEntityOption(entityId: string, domain: string): EntityOption {
  return { entityId, name: entityId, domain, source: 'home_assistant' }
}

function renderEditor({
  value,
  entities,
  handleOnChange = () => {},
  sourceFilter,
}: {
  value: EntityStateValue
  entities: EntityOption[]
  handleOnChange?: (v: EntityStateValue) => void
  sourceFilter?: EntitySource
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
    ...(sourceFilter ? { sourceFilter } : {}),
  } as unknown as ComponentProps<typeof EntityStateValueEditor>
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

  it('AC-11: toggling "Only after alarm state change" reports changedSinceAlarmTransition and keeps entity/equals', () => {
    const handleOnChange = vi.fn()
    const entities = [makeEntityOption('binary_sensor.front_door', 'binary_sensor')]
    const { getByLabelText } = renderEditor({
      value: { entityId: 'binary_sensor.front_door', equals: 'on' },
      entities,
      handleOnChange,
    })
    const box = getByLabelText('Only after alarm state change') as HTMLInputElement
    expect(box.checked).toBe(false)
    fireEvent.click(box)
    expect(handleOnChange).toHaveBeenCalledWith({
      entityId: 'binary_sensor.front_door',
      equals: 'on',
      changedSinceAlarmTransition: true,
    })

    const onChangeAgain = vi.fn()
    const second = renderEditor({
      value: { entityId: 'binary_sensor.front_door', equals: 'on', changedSinceAlarmTransition: true },
      entities,
      handleOnChange: onChangeAgain,
    })
    // Scope to this render's container: the first editor is still mounted in document.body.
    const checked = within(second.container).getByLabelText('Only after alarm state change') as HTMLInputElement
    expect(checked.checked).toBe(true)
    fireEvent.click(checked)
    expect(onChangeAgain).toHaveBeenCalledWith({
      entityId: 'binary_sensor.front_door',
      equals: 'on',
      changedSinceAlarmTransition: false,
    })
  })

  it('offers "Only after alarm state change" for Home Assistant entities only', () => {
    const label = 'Only after alarm state change'
    const ha = renderEditor({
      value: { entityId: '', equals: 'on' },
      entities: [],
      sourceFilter: 'home_assistant',
    })
    expect(within(ha.container).queryByLabelText(label)).not.toBeNull()
    expect(within(ha.container).getByLabelText("About 'Only after alarm state change'")).toBeTruthy()

    const zwave = renderEditor({
      value: { entityId: 'zwavejs.node_5_door', equals: 'on' },
      entities: [{ entityId: 'zwavejs.node_5_door', name: 'Door', domain: 'binary_sensor', source: 'zwavejs' }],
    })
    expect(within(zwave.container).queryByLabelText(label)).toBeNull()

    const z2m = renderEditor({
      value: { entityId: 'z2m_binary_sensor.abc_contact', equals: 'on' },
      entities: [],
      sourceFilter: 'zigbee2mqtt',
    })
    expect(within(z2m.container).queryByLabelText(label)).toBeNull()

    const unresolved = renderEditor({ value: { entityId: '', equals: 'on' }, entities: [] })
    expect(within(unresolved.container).queryByLabelText(label)).toBeNull()
  })

  it('drops the flag when the picker switches to a non-HA entity, and keeps a stored flag visible', () => {
    const label = 'Only after alarm state change'
    const entities: EntityOption[] = [
      makeEntityOption('binary_sensor.front_door', 'binary_sensor'),
      { entityId: 'zwavejs.node_5_door', name: 'Z-Wave door', domain: 'binary_sensor', source: 'zwavejs' },
    ]
    const handleOnChange = vi.fn()
    const { container } = renderEditor({
      value: { entityId: 'binary_sensor.front_door', equals: 'on', changedSinceAlarmTransition: true },
      entities,
      handleOnChange,
    })
    const trigger = container.querySelector<HTMLButtonElement>('button[aria-haspopup="listbox"]')
    if (!trigger) throw new Error('entity picker trigger not found')
    fireEvent.click(trigger)
    fireEvent.click(within(container).getByRole('option', { name: /zwavejs\.node_5_door/ }))
    expect(handleOnChange).toHaveBeenCalledWith({ entityId: 'zwavejs.node_5_door', equals: 'on' })

    // A flag already stored on a non-HA entity stays visible and can be cleared.
    const onClear = vi.fn()
    const stored = renderEditor({
      value: { entityId: 'zwavejs.node_5_door', equals: 'on', changedSinceAlarmTransition: true },
      entities,
      handleOnChange: onClear,
    })
    const box = within(stored.container).getByLabelText(label) as HTMLInputElement
    expect(box.checked).toBe(true)
    fireEvent.click(box)
    expect(onClear).toHaveBeenCalledWith({
      entityId: 'zwavejs.node_5_door',
      equals: 'on',
      changedSinceAlarmTransition: false,
    })
  })
})
