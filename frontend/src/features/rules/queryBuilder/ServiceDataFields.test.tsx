import React from 'react'
import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { ServiceDataFields } from './ServiceDataFields'
import type { HomeAssistantServiceField } from '@/services/homeAssistant'

// react-colorful's picker is pointer-driven, which jsdom can't exercise;
// stub it with a button that emits one fixed color.
vi.mock('react-colorful', () => ({
  RgbColorPicker: ({ onChange }: { onChange: (color: { r: number; g: number; b: number }) => void }) => (
    <button type="button" onClick={() => onChange({ r: 232, g: 52, b: 28 })}>
      mock-color-picker
    </button>
  ),
}))

const FIELDS: Record<string, HomeAssistantServiceField> = {
  brightnessPct: {
    name: 'Brightness',
    selector: { number: { min: 0, max: 100, unitOfMeasurement: '%' } },
  },
  rgbColor: { name: 'Color', selector: { colorRgb: null } },
  flash: { name: 'Flash', selector: { select: { options: ['long', 'short'] } } },
  message: { name: 'Message', required: true, selector: { text: null } },
  enabled: { name: 'Enabled', selector: { boolean: null } },
  // No widget maps to HA's generic object selector; JSON-editable only.
  advancedThing: { name: 'Advanced thing', selector: { object: null } },
}

describe('ServiceDataFields', () => {
  it('writes a parsed number and preserves unrelated data keys', () => {
    const onChange = vi.fn()
    render(
      <ServiceDataFields fields={FIELDS} data={{ rgbColor: [1, 2, 3] }} onChange={onChange} />
    )

    fireEvent.change(screen.getByRole('spinbutton', { name: 'Brightness' }), {
      target: { value: '50' },
    })
    expect(onChange).toHaveBeenCalledWith({ rgbColor: [1, 2, 3], brightnessPct: 50 })
  })

  it('removes the key when a number input is cleared', () => {
    const onChange = vi.fn()
    render(<ServiceDataFields fields={FIELDS} data={{ brightnessPct: 50 }} onChange={onChange} />)

    fireEvent.change(screen.getByRole('spinbutton', { name: 'Brightness' }), {
      target: { value: '' },
    })
    expect(onChange).toHaveBeenCalledWith({})
  })

  it('toggles a boolean field via the switch', () => {
    const onChange = vi.fn()
    render(<ServiceDataFields fields={FIELDS} data={{}} onChange={onChange} />)

    fireEvent.click(screen.getByRole('switch', { name: 'Enabled' }))
    expect(onChange).toHaveBeenCalledWith({ enabled: true })
  })

  it('writes the chosen select option and deletes the key when cleared', () => {
    const onChange = vi.fn()
    const { rerender } = render(
      <ServiceDataFields fields={FIELDS} data={{}} onChange={onChange} />
    )

    fireEvent.change(screen.getByRole('combobox', { name: 'Flash' }), {
      target: { value: 'long' },
    })
    expect(onChange).toHaveBeenCalledWith({ flash: 'long' })

    rerender(<ServiceDataFields fields={FIELDS} data={{ flash: 'long' }} onChange={onChange} />)
    fireEvent.change(screen.getByRole('combobox', { name: 'Flash' }), { target: { value: '' } })
    expect(onChange).toHaveBeenLastCalledWith({})
  })

  it('writes text fields as strings', () => {
    const onChange = vi.fn()
    render(<ServiceDataFields fields={FIELDS} data={{}} onChange={onChange} />)

    fireEvent.change(screen.getByRole('textbox', { name: 'Message' }), {
      target: { value: 'Alarm triggered' },
    })
    expect(onChange).toHaveBeenCalledWith({ message: 'Alarm triggered' })
  })

  it('does not render fields with unsupported selectors', () => {
    render(<ServiceDataFields fields={FIELDS} data={{}} onChange={vi.fn()} />)
    expect(screen.queryByText('Advanced thing')).toBeNull()
  })

  it('renders nothing when no field has a supported selector', () => {
    const { container } = render(
      <ServiceDataFields
        fields={{ advancedThing: FIELDS.advancedThing }}
        data={{}}
        onChange={vi.fn()}
      />
    )
    expect(container).toBeEmptyDOMElement()
  })

  // ── colorRgb widget (ADR-0101 AC-5) ────────────────────────────────────────

  it('shows the current rgb triplet and writes [r, g, b] when a color is picked', () => {
    const onChange = vi.fn()
    render(
      <ServiceDataFields fields={FIELDS} data={{ rgbColor: [255, 0, 0] }} onChange={onChange} />
    )

    expect(screen.getByText('[255, 0, 0]')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Pick Color' }))
    fireEvent.click(screen.getByRole('button', { name: 'mock-color-picker' }))
    expect(onChange).toHaveBeenCalledWith({ rgbColor: [232, 52, 28] })
  })

  it('clears the rgb key via the Clear button', () => {
    const onChange = vi.fn()
    render(
      <ServiceDataFields fields={FIELDS} data={{ rgbColor: [255, 0, 0] }} onChange={onChange} />
    )

    fireEvent.click(screen.getByRole('button', { name: 'Clear' }))
    expect(onChange).toHaveBeenCalledWith({})
  })

  it('shows "not set" when the data value is not a valid rgb triplet', () => {
    render(<ServiceDataFields fields={FIELDS} data={{ rgbColor: 'red' }} onChange={vi.fn()} />)
    expect(screen.getByText('not set')).toBeInTheDocument()
  })
})
