import { useCallback, useRef, useState } from 'react'
import { Pause, Play, Trash2, ArrowDownToLine, Search, X } from 'lucide-react'
import type { SearchAddon } from '@xterm/addon-search'

import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { LOG_LEVELS } from '../types'

const SEARCH_DECORATIONS = {
  matchBackground: '#3f3f46',
  matchBorder: '#52525b',
  matchOverviewRuler: '#888888',
  activeMatchBackground: '#854d0e',
  activeMatchBorder: '#a16207',
  activeMatchColorOverviewRuler: '#ffa500',
} as const

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
  searchAddon: SearchAddon | null
  onPauseToggle: () => void
  onAutoScrollToggle: () => void
  onLevelFilterChange: (level: number) => void
  onClear: () => void
}

export function LogToolbar({
  paused,
  autoScroll,
  levelFilter,
  searchAddon,
  onPauseToggle,
  onAutoScrollToggle,
  onLevelFilterChange,
  onClear,
}: LogToolbarProps) {
  const [searchOpen, setSearchOpen] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const inputRef = useRef<HTMLInputElement>(null)

  const handleSearchToggle = useCallback(() => {
    setSearchOpen((prev) => {
      if (!prev) {
        // Opening search — focus the input after render
        setTimeout(() => inputRef.current?.focus(), 0)
      } else {
        // Closing search — clear highlights
        setSearchQuery('')
        searchAddon?.clearDecorations()
      }
      return !prev
    })
  }, [searchAddon])

  const handleSearchChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const value = e.target.value
      setSearchQuery(value)
      if (value) {
        searchAddon?.findNext(value, { incremental: true, decorations: SEARCH_DECORATIONS })
      } else {
        searchAddon?.clearDecorations()
      }
    },
    [searchAddon]
  )

  const handleSearchKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLInputElement>) => {
      if (e.key === 'Enter') {
        e.preventDefault()
        if (e.shiftKey) {
          searchAddon?.findPrevious(searchQuery, { decorations: SEARCH_DECORATIONS })
        } else {
          searchAddon?.findNext(searchQuery, { decorations: SEARCH_DECORATIONS })
        }
      } else if (e.key === 'Escape') {
        handleSearchToggle()
      }
    },
    [searchAddon, searchQuery, handleSearchToggle]
  )

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

      {/* Search */}
      {searchOpen && (
        <div className="flex items-center gap-1">
          <input
            ref={inputRef}
            type="text"
            value={searchQuery}
            onChange={handleSearchChange}
            onKeyDown={handleSearchKeyDown}
            placeholder="Search logs..."
            className="h-7 w-48 rounded border border-border bg-background px-2 text-xs text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring"
          />
          <Button variant="ghost" size="icon" className="h-7 w-7" onClick={handleSearchToggle}>
            <X className="h-3.5 w-3.5" />
          </Button>
        </div>
      )}

      <Button
        variant="ghost"
        size="icon"
        className="h-7 w-7"
        onClick={handleSearchToggle}
        title="Search (Ctrl+F)"
      >
        <Search className="h-3.5 w-3.5" />
      </Button>

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
