import { Outlet } from 'react-router-dom'
import { Header } from './Header'
import { Sidebar } from './Sidebar'
import { MobileNav } from './MobileNav'
import { AlarmRealtimeProvider } from '@/components/providers/AlarmRealtimeProvider'
import { ConnectionStatusBanner } from '@/components/ui/ConnectionStatusBanner'
import { useLayoutStore } from '@/stores/layoutStore'
import { cn } from '@/lib/utils'

export function AppShell() {
  const sidebarOpen = useLayoutStore((s) => s.sidebarOpen)
  const sidebarCollapsed = useLayoutStore((s) => s.sidebarCollapsed)

  return (
    <div className="min-h-screen bg-background">
      <AlarmRealtimeProvider />
      <Sidebar />
      {/* Main Content */}
      <div
        className={cn(
          'flex flex-col',
          sidebarOpen && (sidebarCollapsed ? 'lg:pl-16' : 'lg:pl-64')
        )}
      >
        <Header />
        <main className="flex-1 p-4 md:p-6 lg:p-8 pb-20 lg:pb-8">
          <Outlet />
        </main>
      </div>
      <MobileNav />
      <ConnectionStatusBanner />
    </div>
  )
}

export default AppShell
