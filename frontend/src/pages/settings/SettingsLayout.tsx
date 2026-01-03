import { NavLink, Outlet } from 'react-router-dom'

import { Page } from '@/components/layout'
import { cn } from '@/lib/utils'

const tabs = [
  { to: 'alarm', label: 'Alarm' },
  { to: 'notifications', label: 'Notifications' },
  { to: 'home-assistant', label: 'Home Assistant' },
  { to: 'mqtt', label: 'MQTT' },
  { to: 'frigate', label: 'Frigate' },
  { to: 'zwavejs', label: 'Z-Wave JS' },
] as const

export function SettingsLayout() {
  return (
    <Page title="Settings">
      <nav className="flex flex-wrap gap-2 border-b border-border pb-2">
        {tabs.map((tab) => (
          <NavLink
            key={tab.to}
            to={tab.to}
            className={({ isActive }) =>
              cn(
                'rounded-md px-3 py-1.5 text-sm font-medium transition-colors',
                isActive
                  ? 'bg-secondary text-secondary-foreground'
                  : 'text-muted-foreground hover:bg-secondary/50 hover:text-foreground'
              )
            }
          >
            {tab.label}
          </NavLink>
        ))}
      </nav>

      <Outlet />
    </Page>
  )
}

export default SettingsLayout
