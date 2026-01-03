import React, { useState } from 'react'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { PushbulletProviderForm } from '@/features/notifications/components/PushbulletProviderForm'

const validate = vi.fn()
const devicesByToken = vi.fn()
const devicesByProvider = vi.fn()

vi.mock('@/services/notifications', () => {
  return {
    notificationsService: {
      validatePushbulletToken: (token: string) => validate(token),
      getPushbulletDevices: (token: string) => devicesByToken(token),
      getPushbulletDevicesByProvider: (id: string) => devicesByProvider(id),
    },
  }
})

describe('PushbulletProviderForm', () => {
  beforeEach(() => {
    validate.mockReset().mockResolvedValue({
      valid: true,
      user: { name: 'Alice', email: 'alice@example.com' },
    })
    devicesByToken.mockReset().mockResolvedValue([
      { iden: 'd1', nickname: 'Phone', model: 'X', pushable: true },
    ])
    devicesByProvider.mockReset().mockResolvedValue([
      { iden: 'd2', nickname: 'Tablet', model: '', pushable: true },
    ])
  })

  it('validates token on blur and shows authenticated user', async () => {
    const user = userEvent.setup()
    render(<Harness initial={{ accessToken: '', targetType: 'all' }} />)

    const token = screen.getByLabelText(/access token/i)
    await user.type(token, 'o.token')
    await waitFor(() => expect(token).toHaveValue('o.token'))
    fireEvent.blur(token)

    await waitFor(() => expect(validate).toHaveBeenCalledWith('o.token'))
    expect(await screen.findByText(/authenticated as:/i)).toBeInTheDocument()
  })

  it('fetches devices using provider id when editing', async () => {
    const user = userEvent.setup()
    render(<Harness initial={{ accessToken: 'o.token', targetType: 'device', defaultDeviceIden: '' }} existingProviderId="p1" />)

    // Ensure device target UI is active
    await user.selectOptions(screen.getByLabelText(/default target/i), ['device'])
    await user.click(screen.getByRole('button', { name: /fetch devices/i }))
    expect(devicesByProvider).toHaveBeenCalledWith('p1')
    expect(await screen.findByRole('option', { name: /tablet/i })).toBeInTheDocument()
  })

  it('switching target type clears unrelated target fields', async () => {
    const user = userEvent.setup()
    render(
      <Harness
        initial={{ accessToken: 'o.token', targetType: 'email', defaultEmail: 'x@example.com', defaultChannelTag: 'c' } as any}
      />
    )

    await user.selectOptions(screen.getByLabelText(/default target/i), ['channel'])
    // After switching, email field should no longer be visible.
    expect(screen.queryByLabelText(/email address/i)).toBeNull()
  })
})

function Harness({ initial, existingProviderId }: { initial: any; existingProviderId?: string }) {
  const [config, setConfig] = useState(initial)
  return <PushbulletProviderForm config={config} onChange={setConfig} existingProviderId={existingProviderId} />
}
