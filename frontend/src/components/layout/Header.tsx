import { Bell, User, LogOut, Moon, Sun, Monitor, House } from 'lucide-react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useThemeStore } from '@/stores/themeStore'
import { alarmService } from '@/services'
import { queryKeys } from '@/types'
import { useWebSocketStatus } from '@/hooks/useWebSocketStatus'
import { useAuthSessionQuery, useCurrentUserQuery, useLogoutMutation } from '@/hooks/useAuthQueries'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { IconButton } from '@/components/ui/icon-button'
import { AlarmStateLabels, AlarmState, Routes } from '@/lib/constants'

export function Header() {
  const logoutMutation = useLogoutMutation()
  const sessionQuery = useAuthSessionQuery()
  const currentUserQuery = useCurrentUserQuery()
  const user = currentUserQuery.data ?? null
  const isAuthenticated = sessionQuery.data.isAuthenticated
  const { theme, setTheme } = useThemeStore()

  const alarmStateQuery = useQuery({
    queryKey: queryKeys.alarm.state,
    queryFn: alarmService.getState,
    enabled: isAuthenticated,
  })
  const alarmState = alarmStateQuery.data ?? null

  const wsStatus = useWebSocketStatus().data

  const currentState = alarmState?.currentState ?? AlarmState.DISARMED

  const getStateBadgeClasses = () => {
    switch (currentState) {
      case AlarmState.DISARMED:
        return 'bg-highlight text-critical'
      case AlarmState.TRIGGERED:
        return 'bg-critical text-white'
      case AlarmState.ARMED_AWAY:
        return 'bg-danger text-white'
      case AlarmState.PENDING:
      case AlarmState.ARMING:
      case AlarmState.ARMED_HOME:
        return 'bg-warning text-critical'
      default:
        return 'bg-highlight text-critical'
    }
  }

  const cycleTheme = () => {
    const themes: Array<'light' | 'dark' | 'system'> = ['light', 'dark', 'system']
    const currentIndex = themes.indexOf(theme)
    const nextIndex = (currentIndex + 1) % themes.length
    setTheme(themes[nextIndex])
  }

  const ThemeIcon = theme === 'dark' ? Moon : theme === 'light' ? Sun : Monitor

  return (
    <header className="flex h-16 items-center gap-4 border-b bg-success px-4 md:px-6 text-white">
      {/* Home */}
      <IconButton asChild aria-label="Home" className="text-white hover:bg-white/10">
        <Link to={Routes.HOME} aria-label="Home">
          <House className="h-5 w-5" />
        </Link>
      </IconButton>

      {/* Alarm Status Badge */}
      <div className="flex items-center gap-2">
        <Badge className={`text-xs ${getStateBadgeClasses()}`}>
          {AlarmStateLabels[currentState]}
        </Badge>
        {wsStatus !== 'connected' && (
          <Badge variant="outline" className="text-xs border-white/50 text-white/80">
            {wsStatus === 'connecting' ? 'Connecting...' : 'Offline'}
          </Badge>
        )}
      </div>

      {/* Spacer */}
      <div className="flex-1" />

      {/* Right side controls */}
      <div className="flex items-center gap-2">
        {/* Theme Toggle */}
        <IconButton onClick={cycleTheme} aria-label="Toggle theme" className="text-white hover:bg-white/10">
          <ThemeIcon className="h-5 w-5" />
        </IconButton>

        {/* Notifications */}
        <IconButton className="relative text-white hover:bg-white/10" aria-label="Notifications">
          <Bell className="h-5 w-5" />
        </IconButton>

        {/* User Menu */}
        <div className="flex items-center gap-2">
          <Button variant="ghost" size="sm" className="hidden md:flex gap-2 text-white hover:bg-white/10 hover:text-white">
            <User className="h-4 w-4" />
            <span>{user?.displayName || 'User'}</span>
          </Button>
          <Button
            variant="ghost"
            size="icon"
            onClick={() => logoutMutation.mutateAsync()}
            title="Logout"
            className="text-white hover:bg-white/10 hover:text-white"
          >
            <LogOut className="h-5 w-5" />
            <span className="sr-only">Logout</span>
          </Button>
        </div>
      </div>
    </header>
  )
}

export default Header
