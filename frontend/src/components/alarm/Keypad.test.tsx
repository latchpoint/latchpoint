import React from 'react'
import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Keypad } from './Keypad'

describe('Keypad', () => {
  it('builds a code and submits it', async () => {
    const user = userEvent.setup()
    const onSubmit = vi.fn()

    render(<Keypad onSubmit={onSubmit} onCancel={vi.fn()} />)

    await user.click(screen.getByRole('button', { name: '1' }))
    await user.click(screen.getByRole('button', { name: '2' }))
    expect(screen.getByText('••')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /submit/i }))
    expect(onSubmit).toHaveBeenCalledWith('12')
    expect(screen.getByText(/enter code/i)).toBeInTheDocument()
  })

  it('supports delete, clear, and cancel', async () => {
    const user = userEvent.setup()
    const onSubmit = vi.fn()
    const onCancel = vi.fn()

    render(<Keypad onSubmit={onSubmit} onCancel={onCancel} />)

    await user.click(screen.getByRole('button', { name: '1' }))
    await user.click(screen.getByRole('button', { name: '2' }))
    await user.click(screen.getByRole('button', { name: /delete/i }))
    expect(screen.getByText('•')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /clear/i }))
    expect(screen.getByText(/enter code/i)).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /cancel/i }))
    expect(onCancel).toHaveBeenCalled()
    expect(screen.getByText(/enter code/i)).toBeInTheDocument()
  })
})
