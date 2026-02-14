import { Pause, Play, Trash2, ArrowDownToLine } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { LOG_LEVELS } from '../types'

const LEVEL_OPTIONS: { label: string; value: number }[] = [
  { label: 'All', value: 0 },
  { label: 'Debug', value: LOG_LEVELS.DEBUG },
  { label: 'Info', value: LOG_LEVELS.INFO },
  { label: 'Warning', value: LOG_LEVELS.WARNING },
  { label: 'Error', value: LOG_LEVELS.ERROR },
  { label: 'Critical', value: LOG_LEVELS.CRITICAL },
]

interface LogToolbarProps {
  paused: boolean
  autoScroll: boolean
  levelFilter: number
  onPauseToggle: () => void
  onAutoScrollToggle: () => void
  onLevelFilterChange: (level: number) => void
  onClear: () => void
}

export function LogToolbar({
  paused,
  autoScroll,
  levelFilter,
  onPauseToggle,
  onAutoScrollToggle,
  onLevelFilterChange,
  onClear,
}: LogToolbarProps) {
  return (
    <div className="flex flex-wrap items-center gap-2 px-3 py-2 border-b border-border bg-card">
      {/* Level filter */}
      <div className="flex items-center gap-1">
        {LEVEL_OPTIONS.map((opt) => (
          <button
            key={opt.value}
            onClick={() => onLevelFilterChange(opt.value)}
            className={cn(
              'rounded px-2 py-0.5 text-xs font-medium transition-colors',
              levelFilter === opt.value
                ? 'bg-primary text-primary-foreground'
                : 'text-muted-foreground hover:bg-secondary hover:text-secondary-foreground'
            )}
          >
            {opt.label}
          </button>
        ))}
      </div>

      <div className="flex-1" />

      {/* Auto-scroll toggle */}
      <Button
        variant="ghost"
        size="icon"
        className={cn('h-7 w-7', autoScroll && 'text-primary')}
        onClick={onAutoScrollToggle}
        title={autoScroll ? 'Auto-scroll: on' : 'Auto-scroll: off'}
      >
        <ArrowDownToLine className="h-3.5 w-3.5" />
      </Button>

      {/* Pause/Resume */}
      <Button
        variant="ghost"
        size="icon"
        className={cn('h-7 w-7', paused && 'text-yellow-500')}
        onClick={onPauseToggle}
        title={paused ? 'Resume streaming' : 'Pause streaming'}
      >
        {paused ? <Play className="h-3.5 w-3.5" /> : <Pause className="h-3.5 w-3.5" />}
      </Button>

      {/* Clear */}
      <Button variant="ghost" size="icon" className="h-7 w-7" onClick={onClear} title="Clear logs">
        <Trash2 className="h-3.5 w-3.5" />
      </Button>
    </div>
  )
}
