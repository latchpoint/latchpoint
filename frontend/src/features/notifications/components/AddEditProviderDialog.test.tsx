import React from 'react'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AddEditProviderDialog } from '@/features/notifications/components/AddEditProviderDialog'
import { waitFor } from '@testing-library/react'

const create = vi.fn().mockResolvedValue({ id: 'new' })
const update = vi.fn().mockResolvedValue({ id: 'p1' })

vi.mock('@/features/notifications/hooks/useNotificationProviders', () => {
  return {
    useCreateNotificationProvider: () => ({ isPending: false, mutateAsync: create }),
    useUpdateNotificationProvider: () => ({ isPending: false, mutateAsync: update }),
  }
})

vi.mock('@/components/ui/modal', () => {
  return {
    Modal: (props: any) => (props.open ? <div><div>{props.title}</div>{props.children}</div> : null),
  }
})

vi.mock('./PushbulletProviderForm', () => {
  return {
    PushbulletProviderForm: () => <div>PushbulletProviderForm</div>,
  }
})

describe('AddEditProviderDialog', () => {
  beforeEach(() => {
    create.mockClear()
    update.mockClear()
  })

  it('validates name required', async () => {
    const user = userEvent.setup()
    render(<AddEditProviderDialog open={true} onClose={() => {}} provider={null} />)

    await user.click(screen.getByRole('button', { name: /add provider/i }))
    expect(screen.getByText(/name is required/i)).toBeInTheDocument()
    expect(create).not.toHaveBeenCalled()
  })

  it('creates provider and closes', async () => {
    const user = userEvent.setup()
    const onClose = vi.fn()
    render(<AddEditProviderDialog open={true} onClose={onClose} provider={null} />)

    await user.type(screen.getByLabelText(/display name/i), 'PB')
    await user.click(screen.getByRole('button', { name: /add provider/i }))

    expect(create).toHaveBeenCalled()
    await waitFor(() => expect(onClose).toHaveBeenCalled())
  })

  it('updates provider when editing', async () => {
    const user = userEvent.setup()
    const onClose = vi.fn()
    render(
      <AddEditProviderDialog
        open={true}
        onClose={onClose}
        provider={{ id: 'p1', name: 'Old', providerType: 'webhook', config: { url: 'x' }, isEnabled: true, createdAt: '', updatedAt: '' } as any}
      />
    )

    const input = screen.getByLabelText(/display name/i)
    await user.clear(input)
    await user.type(input, 'New')
    await user.click(screen.getByRole('button', { name: /save changes/i }))

    expect(update).toHaveBeenCalledWith({ id: 'p1', data: expect.objectContaining({ name: 'New' }) })
    await waitFor(() => expect(onClose).toHaveBeenCalled())
  })
})
