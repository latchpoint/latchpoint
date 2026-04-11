import { describe, expect, it, vi, beforeEach } from 'vitest'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderWithProviders } from '@/test/render'
import { NotificationProvidersCard } from '@/features/notifications/components/NotificationProvidersCard'
import type { NotificationProvider } from '@/types/notifications'

const mutateTest = vi.fn()
const mutateDelete = vi.fn()

let providersData: NotificationProvider[] = []
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
    useTestNotificationProvider: () => ({ mutateAsync: mutateTest, isPending: false }),
    useDeleteNotificationProvider: () => ({ mutateAsync: mutateDelete, isPending: false }),
    useNotificationProviderTypes: () => ({ data: [], isLoading: false }),
    useCreateNotificationProvider: () => ({ mutateAsync: vi.fn(), isPending: false }),
    useUpdateNotificationProvider: () => ({ mutateAsync: vi.fn(), isPending: false }),
  }
})

describe('NotificationProvidersCard', () => {
  beforeEach(() => {
    providersData = [
      { id: 'p1', name: 'PB', providerType: 'pushbullet', config: {}, isEnabled: true, createdAt: '', updatedAt: '' },
    ]
    haConfigured = false
    mutateTest.mockReset().mockResolvedValue({ success: true, message: 'OK' })
    mutateDelete.mockReset().mockResolvedValue(undefined)
  })

  it('renders virtual Home Assistant system provider when HA configured', () => {
    haConfigured = true
    renderWithProviders(<NotificationProvidersCard />)
    expect(screen.getAllByText('Home Assistant').length).toBeGreaterThanOrEqual(1)
    expect(screen.getByText(/system/i)).toBeInTheDocument()
  })

  it('tests provider and displays result banner', async () => {
    const user = userEvent.setup()
    renderWithProviders(<NotificationProvidersCard />)

    await user.click(screen.getByRole('button', { name: /test/i }))
    expect(mutateTest).toHaveBeenCalledWith('p1')
    expect(await screen.findByText('OK')).toBeInTheDocument()
  })

  it('renders Add button for creating providers', () => {
    renderWithProviders(<NotificationProvidersCard />)
    expect(screen.getByRole('button', { name: /add/i })).toBeInTheDocument()
  })
})
