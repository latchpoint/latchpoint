import * as React from 'react'
import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'

import { TemplateVariablePicker } from './TemplateVariablePicker'

function Harness({ initial = '' }: { initial?: string }) {
  const [value, setValue] = React.useState(initial)
  const ref = React.useRef<HTMLTextAreaElement>(null)
  return (
    <div>
      <textarea ref={ref} value={value} onChange={(e) => setValue(e.target.value)} aria-label="message" />
      <TemplateVariablePicker inputRef={ref} value={value} onChange={setValue} />
    </div>
  )
}

describe('TemplateVariablePicker', () => {
  it('renders the primary chip set with monospaced labels', () => {
    render(<Harness />)
    expect(screen.getByRole('button', { name: 'Insert {{trigger.name}}' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Insert {{trigger.entity_id}}' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Insert {{trigger.state}}' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Insert {{rule.name}}' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Insert {{now}}' })).toBeInTheDocument()
  })

  it('inserts the token at the end of the field when cursor is at end', () => {
    render(<Harness initial="Alarm by " />)
    const textarea = screen.getByLabelText('message') as HTMLTextAreaElement
    textarea.focus()
    textarea.setSelectionRange(textarea.value.length, textarea.value.length)
    fireEvent.click(screen.getByRole('button', { name: 'Insert {{trigger.name}}' }))
    expect(textarea.value).toBe('Alarm by {{trigger.name}}')
  })

  it('inserts the token at the current cursor selection', () => {
    render(<Harness initial="A B" />)
    const textarea = screen.getByLabelText('message') as HTMLTextAreaElement
    textarea.focus()
    textarea.setSelectionRange(2, 2) // between space and B
    fireEvent.click(screen.getByRole('button', { name: 'Insert {{rule.name}}' }))
    expect(textarea.value).toBe('A {{rule.name}}B')
  })

  it('replaces the selected range with the token', () => {
    render(<Harness initial="hello world" />)
    const textarea = screen.getByLabelText('message') as HTMLTextAreaElement
    textarea.focus()
    textarea.setSelectionRange(6, 11) // selects "world"
    fireEvent.click(screen.getByRole('button', { name: 'Insert {{trigger.entity_id}}' }))
    expect(textarea.value).toBe('hello {{trigger.entity_id}}')
  })

  it('exposes a help affordance with aria-label', () => {
    render(<Harness />)
    expect(screen.getByLabelText('Available template variables')).toBeInTheDocument()
  })

  it('disables chips when disabled prop is true', () => {
    function Disabled() {
      const ref = React.useRef<HTMLTextAreaElement>(null)
      return (
        <>
          <textarea ref={ref} aria-label="message" />
          <TemplateVariablePicker inputRef={ref} value="" onChange={vi.fn()} disabled />
        </>
      )
    }
    render(<Disabled />)
    expect(screen.getByRole('button', { name: 'Insert {{trigger.name}}' })).toBeDisabled()
  })
})
