import React from 'react'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderWithProviders } from '@/test/render'
import { NotificationProvidersCard } from '@/features/notifications/components/NotificationProvidersCard'
import { HA_SYSTEM_PROVIDER_ID } from '@/lib/constants'

const mutateDelete = vi.fn()
const mutateTest = vi.fn()
const mutateUpdate = vi.fn()

let providersData: any[] = []
let haConfigured = false

vi.mock('@/hooks/useHomeAssistant', () => {
  return {
    useHomeAssistantStatus: () => ({ data: { configured: haConfigured } }),
  }
})

vi.mock('@/features/notifications/hooks/useNotificationProviders', () => {
  return {
    useNotificationProviders: () => ({
      data: providersData,
      isLoading: false,
    }),
    useDeleteNotificationProvider: () => ({ mutateAsync: mutateDelete, isPending: false }),
    useTestNotificationProvider: () => ({ mutateAsync: mutateTest, isPending: false }),
    useUpdateNotificationProvider: () => ({ mutateAsync: mutateUpdate, isPending: false }),
  }
})

vi.mock('@/features/notifications/components/AddEditProviderDialog', () => {
  return {
    AddEditProviderDialog: (props: any) =>
      props.open ? <div>Dialog Open {props.provider?.id ?? 'new'}</div> : null,
  }
})

describe('NotificationProvidersCard', () => {
  beforeEach(() => {
    providersData = [
      { id: 'p1', name: 'PB', providerType: 'pushbullet', config: {}, isEnabled: true, createdAt: '', updatedAt: '' },
    ]
    haConfigured = false
    mutateDelete.mockReset().mockResolvedValue(undefined)
    mutateTest.mockReset().mockResolvedValue({ success: true, message: 'OK' })
    mutateUpdate.mockReset().mockResolvedValue({ id: 'x' })
    vi.stubGlobal('confirm', vi.fn(() => true))
  })

  it('shows Add Provider only for admins and opens dialog', async () => {
    const user = userEvent.setup()
    renderWithProviders(<NotificationProvidersCard isAdmin={false} />)
    expect(screen.queryByRole('button', { name: /add provider/i })).toBeNull()

    renderWithProviders(<NotificationProvidersCard isAdmin={true} />)
    await user.click(screen.getByRole('button', { name: /add provider/i }))
    expect(screen.getByText(/dialog open new/i)).toBeInTheDocument()
  })

  it('renders virtual Home Assistant system provider when HA configured', () => {
    haConfigured = true
    renderWithProviders(<NotificationProvidersCard isAdmin={true} />)
    expect(screen.getAllByText('Home Assistant').length).toBeGreaterThanOrEqual(1)
    expect(screen.getByText(/system/i)).toBeInTheDocument()
  })

  it('tests provider and displays result banner', async () => {
    const user = userEvent.setup()
    renderWithProviders(<NotificationProvidersCard isAdmin={true} />)

    await user.click(screen.getByRole('button', { name: /test/i }))
    expect(mutateTest).toHaveBeenCalledWith('p1')
    expect(await screen.findByText('OK')).toBeInTheDocument()
  })

  it('toggles enabled state via update mutation', async () => {
    const user = userEvent.setup()
    renderWithProviders(<NotificationProvidersCard isAdmin={true} />)

    const toggle = screen.queryByRole('switch') ?? screen.getByRole('checkbox')
    await user.click(toggle)

    expect(mutateUpdate).toHaveBeenCalledWith({ id: 'p1', data: { isEnabled: false } })
  })

  it('deletes provider after confirmation', async () => {
    const user = userEvent.setup()
    renderWithProviders(<NotificationProvidersCard isAdmin={true} />)

    const buttons = screen.getAllByRole('button')
    const deleteButton = buttons.find((b) => b.className.includes('text-destructive'))!
    await user.click(deleteButton)

    expect(mutateDelete).toHaveBeenCalledWith('p1')
  })
})
