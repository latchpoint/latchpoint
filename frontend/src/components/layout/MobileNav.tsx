import { Link, useLocation } from 'react-router-dom'
import { cn } from '@/lib/utils'
import { navItems } from './navItems'

export function MobileNav() {
  const location = useLocation()

  return (
    <nav className="fixed bottom-0 left-0 right-0 z-50 bg-sidebar text-sidebar-foreground border-t border-border lg:hidden">
      <div className="flex items-stretch h-16 overflow-x-auto overflow-y-hidden [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
        {navItems.map((item) => {
          const isActive =
            location.pathname === item.path || location.pathname.startsWith(item.path + '/')
          const Icon = item.icon

          return (
            <Link
              key={item.path}
              to={item.path}
              className={cn(
                'flex shrink-0 flex-col items-center justify-center gap-1 px-3 min-w-[72px] text-center',
                isActive ? 'text-primary' : 'text-muted-foreground'
              )}
            >
              <Icon className="h-5 w-5 shrink-0" aria-hidden />
              <span className="text-[11px] font-medium leading-none whitespace-nowrap">
                {item.label}
              </span>
            </Link>
          )
        })}
      </div>
    </nav>
  )
}

export default MobileNav
