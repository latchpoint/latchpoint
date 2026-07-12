import React from 'react'
import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { ActionPicker } from './ActionPicker'
import type { HomeAssistantServiceDefinition } from '@/services/homeAssistant'

function svc(domain: string, service: string, name = ''): HomeAssistantServiceDefinition {
  return { domain, service, name, description: '', fields: {} }
}

const CATALOG = [
  svc('light', 'turn_on', 'Turn on'),
  svc('light', 'turn_off', 'Turn off'),
  svc('lock', 'lock', 'Lock'),
]

describe('ActionPicker', () => {
  it('renders a plain free-text input when the catalog is empty', () => {
    const onChange = vi.fn()
    render(<ActionPicker value="" onChange={onChange} services={[]} />)

    const input = screen.getByPlaceholderText('e.g., light.turn_on')
    fireEvent.change(input, { target: { value: 'switch.toggle' } })
    expect(onChange).toHaveBeenCalledWith('switch.toggle')
  })

  it('lists catalog actions and filters them by search text', () => {
    render(<ActionPicker value="" onChange={vi.fn()} services={CATALOG} />)

    fireEvent.click(screen.getByRole('button', { name: /select action/i }))
    expect(screen.getAllByRole('option')).toHaveLength(3)

    fireEvent.change(screen.getByPlaceholderText('Search actions...'), {
      target: { value: 'turn_off' },
    })
    expect(screen.getByRole('option', { name: /light\.turn_off/i })).toBeInTheDocument()
    expect(screen.queryByText('lock.lock')).toBeNull()
  })

  it('emits the picked action id and closes the dropdown', () => {
    const onChange = vi.fn()
    render(<ActionPicker value="light.turn_on" onChange={onChange} services={CATALOG} />)

    fireEvent.click(screen.getByRole('button', { name: /light\.turn_on/i }))
    fireEvent.click(screen.getByRole('option', { name: /lock\.lock/i }))

    expect(onChange).toHaveBeenCalledWith('lock.lock')
    expect(screen.queryByRole('listbox')).toBeNull()
  })

  it('offers a "Use" row that commits unmatched search text as a free-text action', () => {
    const onChange = vi.fn()
    render(<ActionPicker value="" onChange={onChange} services={CATALOG} />)

    fireEvent.click(screen.getByRole('button', { name: /select action/i }))
    fireEvent.change(screen.getByPlaceholderText('Search actions...'), {
      target: { value: 'vacuum.start' },
    })

    fireEvent.click(screen.getByRole('option', { name: /use .*vacuum\.start/i }))
    expect(onChange).toHaveBeenCalledWith('vacuum.start')
  })

  it('does not offer a "Use" row when the search exactly matches a catalog action', () => {
    render(<ActionPicker value="" onChange={vi.fn()} services={CATALOG} />)

    fireEvent.click(screen.getByRole('button', { name: /select action/i }))
    fireEvent.change(screen.getByPlaceholderText('Search actions...'), {
      target: { value: 'lock.lock' },
    })

    expect(screen.queryByText(/^use/i)).toBeNull()
    expect(screen.getByRole('option', { name: /lock\.lock/i })).toBeInTheDocument()
  })
})
