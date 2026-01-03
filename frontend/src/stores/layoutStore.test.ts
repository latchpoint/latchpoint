import { describe, expect, it, beforeEach } from 'vitest'
import { useLayoutStore } from '@/stores'

describe('layoutStore', () => {
  beforeEach(() => {
    localStorage.clear()
    useLayoutStore.setState({
      sidebarOpen: true,
      sidebarCollapsed: false,
      isMobile: false,
    } as never)
  })

  it('toggles sidebarOpen', () => {
    const store = useLayoutStore.getState()
    expect(store.sidebarOpen).toBe(true)
    store.toggleSidebar()
    expect(useLayoutStore.getState().sidebarOpen).toBe(false)
  })

  it('persists only sidebarCollapsed', () => {
    const store = useLayoutStore.getState()
    store.setSidebarOpen(false)
    store.setIsMobile(true)
    store.setSidebarCollapsed(true)

    const raw = localStorage.getItem('alarm-layout')
    expect(raw).toContain('sidebarCollapsed')
    expect(raw).not.toContain('sidebarOpen')
    expect(raw).not.toContain('isMobile')
  })
})

