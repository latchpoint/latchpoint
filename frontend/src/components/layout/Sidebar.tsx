import { Link, useLocation } from 'react-router-dom'
import { ChevronLeft, ChevronRight, Github } from 'lucide-react'
import { useLayoutStore } from '@/stores/layoutStore'
import { cn } from '@/lib/utils'
import { Routes } from '@/lib/constants'
import { Button } from '@/components/ui/button'
import { navItems } from './navItems'

const appVersion = __APP_VERSION__
const gitCommit = __GIT_COMMIT__
const repoUrl = __REPO_URL__

export function Sidebar() {
  const location = useLocation()
  const { sidebarOpen, sidebarCollapsed, setSidebarCollapsed } = useLayoutStore()

  if (!sidebarOpen) return null

  return (
    <aside
      className={cn(
        'fixed left-0 top-0 z-40 h-screen bg-sidebar text-sidebar-foreground border-r border-border transition-all duration-300 hidden lg:block',
        sidebarCollapsed ? 'w-16' : 'w-64'
      )}
    >
      {/* Logo */}
      <div className="flex items-center justify-between h-16 px-4 border-b border-border">
        {!sidebarCollapsed && (
          <Link to={Routes.HOME} className="flex items-center gap-2">
            <img src="/latchpoint_brand.png" alt="Latchpoint" className="h-8 w-8 object-contain" />
            <span className="font-semibold text-lg">Latchpoint</span>
          </Link>
        )}
        {sidebarCollapsed && (
          <Link to={Routes.HOME} className="mx-auto">
            <img src="/latchpoint_brand.png" alt="Latchpoint" className="h-8 w-8 object-contain" />
          </Link>
        )}
      </div>

      {/* Navigation */}
      <nav className="flex flex-col gap-1 p-2">
        {navItems.map((item) => {
          const isActive =
            location.pathname === item.path || location.pathname.startsWith(item.path + '/')
          const Icon = item.icon

          return (
            <Link
              key={item.path}
              to={item.path}
              className={cn(
                'flex items-center gap-3 px-3 py-2 rounded-md text-sm font-medium transition-colors',
                isActive
                  ? 'bg-primary text-primary-foreground'
                  : 'text-muted-foreground hover:bg-accent hover:text-accent-foreground',
                sidebarCollapsed && 'justify-center px-2'
              )}
              title={sidebarCollapsed ? item.label : undefined}
            >
              <Icon className="h-5 w-5 shrink-0" />
              {!sidebarCollapsed && <span>{item.label}</span>}
            </Link>
          )
        })}
      </nav>

      {/* Version + Collapse */}
      <div className="absolute bottom-4 left-0 right-0 px-2 space-y-2">
        {!sidebarCollapsed ? (
          <div className="flex items-center justify-between px-3 text-[11px] text-muted-foreground">
            <span>v{appVersion}{gitCommit !== 'dev' ? `+${gitCommit}` : ''}</span>
            <a href={repoUrl} target="_blank" rel="noopener noreferrer" className="hover:text-foreground transition-colors" title="GitHub">
              <Github className="h-3.5 w-3.5" />
            </a>
          </div>
        ) : (
          <div className="flex justify-center">
            <a href={repoUrl} target="_blank" rel="noopener noreferrer" className="text-muted-foreground hover:text-foreground transition-colors" title="GitHub">
              <Github className="h-4 w-4" />
            </a>
          </div>
        )}
        <Button
          variant="ghost"
          size="sm"
          className={cn('w-full', sidebarCollapsed && 'px-2')}
          onClick={() => setSidebarCollapsed(!sidebarCollapsed)}
        >
          {sidebarCollapsed ? (
            <ChevronRight className="h-4 w-4" />
          ) : (
            <>
              <ChevronLeft className="h-4 w-4 mr-2" />
              <span>Collapse</span>
            </>
          )}
        </Button>
      </div>
    </aside>
  )
}

export default Sidebar
