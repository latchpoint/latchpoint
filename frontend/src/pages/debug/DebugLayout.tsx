import { NavLink, Outlet } from 'react-router-dom'

import { Page } from '@/components/layout'
import { cn } from '@/lib/utils'

const tabs = [
  { to: 'entities', label: 'Entities' },
  { to: 'logs', label: 'Logs' },
] as const

export function DebugLayout() {
  return (
    <Page title="Debug" description="Diagnostic tools for inspecting system state.">
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

export default DebugLayout
